/**
 * @file board_pipeline.inc
 * @brief Authored PS-only one-level lookahead scheduler, sharing the serial ABI.
 * @note Included by board_benchmark.c; never an HLS or generated source.
 */
typedef struct {
    const uint8_t* raw;
    uint8_t* blur;
    uint8_t* next;
    OrbPoint* points;
    Fastv2Summary* summary;
    int level;
    uint32_t active;
    int completed;
    uint64_t starts[3];
} NextPipelineLayer;

/** @brief Clear unknown cache ownership of the additional production DMA buffers. */
static void initialize_pipeline_outputs(void) {
    Xil_DCacheFlushRange(NEXT_PIPE_RAW2, NEXT_MAX_PIXELS + 128u);
    Xil_DCacheFlushRange(NEXT_PIPE_BLUR1, NEXT_MAX_PIXELS + 128u);
    Xil_DCacheFlushRange(NEXT_PIPE_POINTS1, 256u * sizeof(OrbPoint) + 128u);
    Xil_DCacheFlushRange(NEXT_PIPE_SUMMARY1, 128u);
}
/**
 * @brief Assign immutable level addresses without allocating or touching payloads.
 * @param layer Receives the level's ownership/launch record.
 * @param level Frozen pyramid level 0..7.
 * @note Three raw slots prevent resize(n+1) overwriting raw(n) during PS(n).
 *       Blur/points/summary alternate because at most two adjacent levels coexist.
 */
static void pipeline_map_layer(NextPipelineLayer* layer, int level) {
    static const uint32_t raw_slots[3] = {NEXT_PYRAMID0, NEXT_PYRAMID1, NEXT_PIPE_RAW2};
    memset(layer, 0, sizeof(*layer));
    layer->level = level;
    layer->raw = (const uint8_t*)(UINTPTR)(level == 0 ? (uint32_t)NEXT_ALIGNED_INPUT : raw_slots[(level - 1) % 3]);
    layer->next = level < 7 ? (uint8_t*)(UINTPTR)raw_slots[level % 3] : NULL;
    layer->blur = (uint8_t*)(UINTPTR)((level & 1) ? (uint32_t)NEXT_PIPE_BLUR1 : (uint32_t)NEXT_BLURRED);
    layer->points = (OrbPoint*)(UINTPTR)((level & 1) ? (uint32_t)NEXT_PIPE_POINTS1 : (uint32_t)NEXT_POINTS);
    layer->summary = (Fastv2Summary*)(UINTPTR)((level & 1) ? (uint32_t)NEXT_PIPE_SUMMARY1 : (uint32_t)NEXT_SUMMARY);
    layer->active = level < 7 ? 7u : 5u;
}
/**
 * @brief Prepare disjoint outputs, configure and launch the next level atomically.
 * @param layer Level ownership record; all preceding uses of its output slots ended.
 * @param mode Verified or Production; Legacy is intentionally serial-only.
 * @param stages Accumulated poison/cache/residual-wait ticks per level.
 * @param config Accumulates MMIO configuration ticks.
 * @param detail Receives level/core diagnostics on failure.
 * @return Zero after launch, or ERR_IDLE without touching any payload.
 */
static int pipeline_launch(NextPipelineLayer* layer, uint32_t mode,
                           uint64_t stages[3][8], uint64_t* config, uint32_t* detail) {
    const int level = layer->level;
    const uint32_t pixels = (uint32_t)(kWidths[level] * kHeights[level]);
    uint64_t mark; int core;
    *detail = (uint32_t)level << 24;
    for (core = 0; core < 3; ++core) if ((layer->active & (1u << core)) &&
        !(Xil_In32(kBases[core] + NEXT_CTRL) & 4u)) { *detail |= 1u << core; return ERR_IDLE; }
    if (mode == NEXT_MODE_VERIFIED) {
        prepare_output(layer->blur, pixels, mode, &stages[0][level], &stages[1][level]);
        prepare_output(layer->points, 256u*sizeof(OrbPoint), mode, &stages[0][level], &stages[1][level]);
        prepare_output(layer->summary, sizeof(Fastv2Summary), mode, &stages[0][level], &stages[1][level]);
        if (layer->next) prepare_output(layer->next, (uint32_t)(kWidths[level+1]*kHeights[level+1]), mode,
                                        &stages[0][level], &stages[1][level]);
    }
    mark = now_ticks();
    configure_front(layer->raw, level, layer->points, layer->summary);
    configure_image(NEXT_GAUSSIAN_BASE, layer->raw, layer->blur, level);
    if (layer->next) configure_image(NEXT_RESIZE_BASE, layer->raw, layer->next, level);
    *config += now_ticks() - mark;
    for (core = 0; core < 3; ++core) if (layer->active & (1u << core)) {
        layer->starts[core] = now_ticks(); Xil_Out32(kBases[core] + NEXT_CTRL, 1);
    }
    return 0;
}
/**
 * @brief Observe each ap_done once and check returns before releasing DMA ownership.
 * @param layer Launched layer; repeated calls after completion are no-ops.
 * @param cores Receives launch-to-observation intervals (upper bounds when PS is busy).
 * @param stages Accumulates only CPU-blocking wait, not already overlapped backend time.
 * @param detail Receives failing level/core mask or return value.
 * @return Zero, ERR_TIMEOUT or ERR_RETURN. Timeout does NOT promise DMA quiescence.
 * @note Ten-second watchdog starts at launch, not after the PS backend finishes.
 */
static int pipeline_complete(NextPipelineLayer* layer, uint64_t cores[3][8],
                             uint64_t stages[3][8], uint32_t* detail) {
    uint32_t pending; uint64_t mark; int core;
    if (layer->completed) return 0;
    pending = layer->active; mark = now_ticks();
    *detail = (uint32_t)layer->level << 24;
    while (pending) {
        for (core = 0; core < 3; ++core) if ((pending & (1u << core)) &&
            (Xil_In32(kBases[core] + NEXT_CTRL) & 2u)) {
            cores[core][layer->level] += now_ticks() - layer->starts[core];
            pending &= ~(1u << core);
        }
        if (pending && now_ticks() - layer->starts[0] >= UINT64_C(10)*COUNTS_PER_SECOND) {
            mailbox()[MB_PENDING_CORE_MASK] = pending;
            *detail |= pending; return ERR_TIMEOUT;
        }
    }
    stages[2][layer->level] += now_ticks() - mark;
    layer->completed = 1;
    for (core = 0; core < 3; ++core) if (layer->active & (1u << core)) {
        const int status = (int)Xil_In32(kBases[core] + NEXT_RETURN);
        if (status) { *detail |= ((uint32_t)core << 16) | ((uint32_t)status & 65535u); return ERR_RETURN; }
    }
    return 0;
}
/**
 * @brief Invalidate only completed DMA buffers before PS consumes them.
 * @param layer Completed current layer; no invalidation is done on a running writer.
 * @param mode Verified also reads resize guards; Production defers next-raw consumption.
 * @param stages Receives cache-maintenance ticks for the current layer.
 */
static void pipeline_collect(const NextPipelineLayer* layer, uint32_t mode, uint64_t stages[3][8]) {
    const int level = layer->level;
    const uint32_t pixels = (uint32_t)(kWidths[level]*kHeights[level]);
    const uint64_t mark = now_ticks();
    if (mode == NEXT_MODE_PRODUCTION && level != 0)
        Xil_DCacheInvalidateRange((INTPTR)layer->raw, (pixels + 63u) & ~63u);
    Xil_DCacheInvalidateRange((INTPTR)layer->blur, (pixels + 127u) & ~63u);
    Xil_DCacheInvalidateRange((INTPTR)layer->points, 256u*sizeof(OrbPoint) + 64u);
    Xil_DCacheInvalidateRange((INTPTR)layer->summary, sizeof(Fastv2Summary) + 64u);
    if (mode == NEXT_MODE_VERIFIED && layer->next)
        Xil_DCacheInvalidateRange((INTPTR)layer->next, ((uint32_t)(kWidths[level+1]*kHeights[level+1]) + 127u) & ~63u);
    stages[1][level] += now_ticks() - mark;
}
/**
 * @brief Keep serial byte-exact oracle/poison acceptance for one pipelined level.
 * @param layer Completed, collected layer whose payload remains exclusively readable.
 * @param raw_ref Independent CPU raw pixels for this level.
 * @param blur_ref Independent CPU Gaussian pixels for this level.
 * @param features Actual PS direction/BRIEF records.
 * @param aggregate Receives the ordered feature digest.
 * @param detail Receives the first useful mismatch index.
 * @return Zero or the same exact-checker error codes as the serial path.
 */
static int pipeline_verify(const NextPipelineLayer* layer, const uint8_t* raw_ref,
                           const uint8_t* blur_ref, const NextFeature* features,
                           uint64_t* aggregate, uint32_t* detail) {
    const int level = layer->level;
    const uint32_t pixels = (uint32_t)(kWidths[level]*kHeights[level]); int index;
    if (memcmp(layer->raw, raw_ref, pixels)) return ERR_RAW;
    if (memcmp(layer->blur, blur_ref, pixels)) return ERR_BLUR;
    if (!check_guard(layer->blur, pixels, 1) || !check_guard((const uint8_t*)layer->points, 256u*sizeof(OrbPoint), 0) ||
        !check_guard((const uint8_t*)layer->summary, sizeof(Fastv2Summary), 0) ||
        (layer->next && !check_guard(layer->next, (uint32_t)(kWidths[level+1]*kHeights[level+1]), 1))) return ERR_GUARD;
    if (memcmp(layer->summary, &kExpectedSummaries[level], sizeof(Fastv2Summary))) return ERR_SUMMARY;
    for (index = 0; index < layer->summary->selected_count; ++index)
        if (memcmp(&layer->points[index], &kExpectedPoints[level][index], sizeof(OrbPoint))) {
            *detail |= (uint32_t)index; return ERR_POINTS;
        }
    for (index = layer->summary->selected_count*(int)sizeof(OrbPoint); index < 256*(int)sizeof(OrbPoint); ++index)
        if (((const uint8_t*)layer->points)[index] != 0xA5) { *detail |= (uint32_t)index; return ERR_GUARD; }
    for (index = 0; index < layer->summary->selected_count; ++index)
        if (memcmp(&features[index], &kExpectedFeatures[level][index], sizeof(NextFeature))) {
            *detail |= (uint32_t)index; return ERR_FEATURE;
        }
    *aggregate = (*aggregate ^ digest((const uint8_t*)features, (size_t)layer->summary->selected_count*sizeof(NextFeature))) * UINT64_C(1099511628211);
    return 0;
}
/**
 * @brief Run PL(n+1) while PS computes descriptors(n), without payload overwrite.
 * @param cores Accumulates per-core observation upper bounds.
 * @param backend Accumulates descriptor computation per level.
 * @param stages Accumulates poison/cache/residual CPU wait, all non-overlapping intervals.
 * @param mode Verified or Production.
 * @param config Accumulates configuration ticks.
 * @param verify Accumulates oracle time ONLY when no PL job is running.
 * @param candidates Receives all-level candidate count for this frame.
 * @param selected Receives all-level feature count for this frame.
 * @param signature Receives exact ordered digest, or zero for unverified production.
 * @param detail Receives level/core/index diagnostics on failure.
 * @return Zero or a stable runtime/verification failure.
 */
static int run_pipeline_frame(uint64_t cores[3][8], uint64_t backend[8], uint64_t stages[3][8],
                              uint32_t mode, uint64_t* config, uint64_t* verify,
                              uint32_t* candidates, uint32_t* selected, uint64_t* signature, uint32_t* detail) {
    NextPipelineLayer layers[8];
    const uint8_t* raw_ref = (const uint8_t*)(UINTPTR)NEXT_REFERENCE_RAW;
    const uint8_t* blur_ref = (const uint8_t*)(UINTPTR)NEXT_REFERENCE_BLUR;
    NextFeature* features = (NextFeature*)(UINTPTR)NEXT_FEATURES;
    uint64_t aggregate = UINT64_C(14695981039346656037); int level, error;
    *candidates = *selected = 0;
    for (level = 0; level < 8; ++level) pipeline_map_layer(&layers[level], level);
    error = pipeline_launch(&layers[0], mode, stages, config, detail);
    if (error) return error;
    for (level = 0; level < 8; ++level) {
        NextPipelineLayer* layer = &layers[level]; uint64_t mark;
        error = pipeline_complete(layer, cores, stages, detail);
        if (error) return error;
        pipeline_collect(layer, mode, stages);
        *detail = (uint32_t)level << 24;
        if (layer->summary->selected_count < 0 || layer->summary->selected_count > 256) return ERR_SUMMARY;
        if (level < 7) {
            error = pipeline_launch(&layers[level+1], mode, stages, config, detail);
            if (error) return error;
            ++mailbox()[MB_BACKEND_AHEAD_LAUNCHES];
        }
        *detail = (uint32_t)level << 24;
        mark = now_ticks();
        error = next_describe(layer->raw, layer->blur, kWidths[level], kHeights[level], layer->points,
                              layer->summary->selected_count, level, features, 256);
        backend[level] += now_ticks() - mark;
        if (error) {
            *detail |= (uint32_t)error & 65535u;
            if (level < 7) {
                uint32_t drain_detail = 0;
                mailbox()[MB_ABORT_DRAIN_ERROR] = (uint32_t)pipeline_complete(&layers[level+1], cores, stages, &drain_detail);
            }
            return ERR_BACKEND;
        }
        if (mode == NEXT_MODE_VERIFIED) {
            /* Do not subtract verification while PL is running: that would create
               optimistic processing FPS and include unmeasured DDR interference. */
            if (level < 7) {
                error = pipeline_complete(&layers[level+1], cores, stages, detail);
                if (error) return error;
            }
            *detail = (uint32_t)level << 24; mark = now_ticks();
            error = pipeline_verify(layer, raw_ref, blur_ref, features, &aggregate, detail);
            *verify += now_ticks() - mark;
            if (error) return error;
        }
        *candidates += (uint32_t)layer->summary->candidate_count;
        *selected += (uint32_t)layer->summary->selected_count;
        raw_ref += kWidths[level]*kHeights[level]; blur_ref += kWidths[level]*kHeights[level];
    }
    *signature = mode == NEXT_MODE_PRODUCTION ? 0 : aggregate;
    return 0;
}
