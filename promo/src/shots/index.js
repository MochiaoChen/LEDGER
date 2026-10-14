// plan.json 的每个镜头 id → 视图。本片的视图是镜头内时间的纯函数（见 kit/time.js），不需要 builder。
import {HookView} from './hook.jsx';
import {BrandView} from './brand.jsx';
import {RuleView} from './rule.jsx';
import {CmdView} from './cmd.jsx';
import {SearchView} from './search.jsx';
import {ReadView} from './read.jsx';
import {CodeView} from './code.jsx';
import {TruthView} from './truth.jsx';
import {ComputeView} from './compute.jsx';
import {DepthView} from './depth.jsx';
import {WriteView} from './write.jsx';
import {ReviewView} from './review.jsx';
import {LayoutView} from './layout.jsx';
import {QcView} from './qc.jsx';
import {CheckView} from './check.jsx';
import {TraceView} from './trace.jsx';
import {EndView} from './end.jsx';
export const SHOT_VIEWS = {hook: HookView, brand: BrandView, rule: RuleView, cmd: CmdView, search: SearchView, read: ReadView, code: CodeView, truth: TruthView,
  depth: DepthView, compute: ComputeView, write: WriteView, review: ReviewView, layout: LayoutView, qc: QcView, check: CheckView, trace: TraceView, end: EndView};
export const SHOT_BUILDERS = {};
