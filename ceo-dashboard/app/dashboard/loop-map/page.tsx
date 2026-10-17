import { TopBar } from "@/components/shell/TopBar";
import { LoopMap } from "@/components/loop-map/LoopMap";

// The Loop Map tab -- next to Marketing. It links to the Outreach lanes on the
// Marketing page for the human steps; it does not replace them.
export default function LoopMapPage() {
  return (
    <div className="flex flex-col h-full min-w-0">
      <TopBar title="Loop Map" />
      <div className="flex-1 overflow-y-auto min-w-0">
        <LoopMap />
      </div>
    </div>
  );
}
