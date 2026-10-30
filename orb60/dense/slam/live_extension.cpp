// This non-virtual member adds a read-only exporter without changing System layout.
#include "System.h"
#include "DenseLiveExport.h"
namespace ORB_SLAM3 {
void System::ExportLiveDenseSnapshot(const std::string& directory) {
    DenseLiveExportAtlas(mpAtlas,directory);
}
}
