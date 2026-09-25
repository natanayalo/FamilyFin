import { Workspace } from "@/components/workspace";
import { DataQualityFeature } from "@/features/data-quality/data-quality-feature";

export default function DataQualityPage() {
  return <Workspace sectionId="data-quality"><DataQualityFeature /></Workspace>;
}
