// SPDX-License-Identifier: GPL-2.0
/* Experimental ACZ7015 UIO provider. No kernel virtual DDR alias is created.
 * Bind only after the generic UIO owner has closed and both PL cores are idle.
 * Control mappings stay Device; only the reserved, no-map DDR uses WC.
 */
#include <linux/atomic.h>
#include <linux/ioport.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/of_address.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/uio_driver.h>

#define ORB60_DDR_BASE 0x20000000UL
#define ORB60_DDR_SIZE 0x01000000UL

static bool write_combine = true;
module_param(write_combine, bool, 0444);
MODULE_PARM_DESC(write_combine, "DDR WC mapping; false is the Device control case");

struct orb60_wc {
	struct uio_info info;
	atomic_t opened;
};

static int orb60_open(struct uio_info *info, struct inode *inode)
{
	struct orb60_wc *state = info->priv;
	return atomic_cmpxchg(&state->opened, 0, 1) ? -EBUSY : 0;
}

static int orb60_release(struct uio_info *info, struct inode *inode)
{
	struct orb60_wc *state = info->priv;
	atomic_set(&state->opened, 0);
	return 0;
}

static int orb60_mmap(struct uio_info *info, struct vm_area_struct *vma)
{
	unsigned long index = vma->vm_pgoff;
	unsigned long bytes = vma->vm_end - vma->vm_start;
	struct uio_mem *mem;

	if (index >= 3 || !bytes || !(vma->vm_flags & VM_SHARED) ||
	    (vma->vm_flags & VM_EXEC))
		return -EINVAL;
	mem = &info->mem[index];
	if (bytes > mem->size)
		return -EINVAL;
	vma->vm_flags |= VM_IO | VM_DONTEXPAND | VM_DONTDUMP;
	if (index == 2 && write_combine)
		vma->vm_page_prot = pgprot_writecombine(vma->vm_page_prot);
	else
		vma->vm_page_prot = pgprot_noncached(vma->vm_page_prot);
	return remap_pfn_range(vma, vma->vm_start, mem->addr >> PAGE_SHIFT,
			       bytes, vma->vm_page_prot);
}

/* Existing DT must explicitly reserve and exclude the entire DDR aperture
 * from the normal linear RAM map. Never apply this driver to Linux RAM.
 */
static bool orb60_ddr_reserved(void)
{
	struct device_node *parent, *node;
	struct resource resource;
	bool found = false;

	parent = of_find_node_by_path("/reserved-memory");
	if (!parent)
		return false;
	for_each_child_of_node(parent, node) {
		if (!of_device_is_available(node) ||
		    !of_property_read_bool(node, "no-map") ||
		    of_address_to_resource(node, 0, &resource))
			continue;
		if (resource.start <= ORB60_DDR_BASE &&
		    resource.end >= ORB60_DDR_BASE + ORB60_DDR_SIZE - 1) {
			found = true;
			of_node_put(node);
			break;
		}
	}
	of_node_put(parent);
	return found;
}

static int orb60_probe(struct platform_device *pdev)
{
	static const unsigned long starts[] = { 0x43c00000, 0x43c10000,
		ORB60_DDR_BASE };
	static const unsigned long sizes[] = { 0x10000, 0x10000,
		ORB60_DDR_SIZE };
	static const char * const names[] = { "layer", "descriptor", "dedicated-ddr" };
	struct orb60_wc *state;
	struct resource resource;
	int index, result;

	if (!pdev->dev.of_node || !orb60_ddr_reserved())
		return -ENODEV;
	state = devm_kzalloc(&pdev->dev, sizeof(*state), GFP_KERNEL);
	if (!state)
		return -ENOMEM;
	for (index = 0; index < 3; ++index) {
		result = of_address_to_resource(pdev->dev.of_node, index, &resource);
		if (result || resource.start != starts[index] ||
		    resource_size(&resource) != sizes[index])
			return -EINVAL;
		if (!devm_request_mem_region(&pdev->dev, resource.start,
					     resource_size(&resource), "orb60-wc-uio"))
			return -EBUSY;
		state->info.mem[index].name = names[index];
		state->info.mem[index].addr = starts[index];
		state->info.mem[index].size = sizes[index];
		state->info.mem[index].memtype = UIO_MEM_PHYS;
	}
	state->info.name = "orb60-writecombine-experiment";
	state->info.version = write_combine ? "wc1" : "nc1";
	state->info.irq = UIO_IRQ_NONE;
	state->info.open = orb60_open;
	state->info.release = orb60_release;
	state->info.mmap = orb60_mmap;
	state->info.priv = state;
	atomic_set(&state->opened, 0);
	platform_set_drvdata(pdev, state);
	result = uio_register_device(&pdev->dev, &state->info);
	if (!result)
		dev_info(&pdev->dev, "reserved DDR %s; controls Device; ABI wc1/nc1\n",
			 write_combine ? "write-combine" : "Device");
	return result;
}

static int orb60_remove(struct platform_device *pdev)
{
	struct orb60_wc *state = platform_get_drvdata(pdev);
	uio_unregister_device(&state->info);
	return 0;
}

/* No generic-uio OF match: production binding is never taken automatically.
 * An explicit temporary driver_override is required for this experiment.
 */
static struct platform_driver orb60_driver = {
	.probe = orb60_probe,
	.remove = orb60_remove,
	.driver = { .name = "orb60_wc_uio", .owner = THIS_MODULE },
};
module_platform_driver(orb60_driver);
MODULE_LICENSE("GPL");
MODULE_AUTHOR("ORB60 project");
MODULE_DESCRIPTION("Bounded reserved-DDR WC versus Device UIO experiment");
