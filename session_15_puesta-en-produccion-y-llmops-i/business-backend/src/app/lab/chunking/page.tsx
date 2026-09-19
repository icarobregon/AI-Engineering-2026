import { corpusSize } from "@/lib/estimator/chunking";
import { ChunkingLab } from "./chunking-lab";

export const dynamic = "force-dynamic";

export default function ChunkingLabPage() {
  return <ChunkingLab corpusSize={corpusSize()} />;
}
