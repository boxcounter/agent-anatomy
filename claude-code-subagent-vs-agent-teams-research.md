# Claude Code Sub-Agent vs Agent Team 模式：社区研究综合报告

> 调查时间：2026-06-18 | 来源：35+ 篇文章 / 讨论 / Issue | 涵盖 Reddit、Hacker News、GitHub、官方文档、技术博客、案例研究

---

## 一、两种模式的架构区别

核心一句话（来自官方文档和几乎所有社区来源）：

> **Sub-agent**：完成任务后结果只汇报给主 agent。**Agent team**：teammate 之间可以直接互相通信。

| 维度 | Sub-agent | Agent Team |
|------|-----------|------------|
| **通信方式** | 星型拓扑：只向主 agent 汇报 | 网状：teammate 之间直接通过 SendMessage 通信 |
| **上下文** | 独立上下文窗口，但共享父 session 的 200K token 预算 | 独立上下文窗口，每个 teammate 是完全独立的 Claude 实例 |
| **协调机制** | 主 agent 集中管理所有工作 | 共享任务列表 + 自协调（含文件锁防竞态） |
| **最适合** | 只需结果的专注任务 | 需要讨论和互相挑战的复杂工作 |
| **Token 成本** | 较低（仅摘要返回主上下文） | 较高（每个 teammate 是独立 Claude 实例，约 3-4x） |
| **状态** | GA | 实验性，需设置 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` |
| **Session 恢复** | 完整可恢复 | /resume 无法恢复 in-process teammate |
| **嵌套** | 支持（最大深度 5，v2.1.172 起） | 不支持（teammate 不能再开子 team） |
| **最大并行数** | 社区实测 50+ sub-agent | 硬件限制：M2 Pro/32GB 上 15 个即崩溃（ZoomInfo 实测） |

**官方架构图的核心信息**：Sub-agent 和 Agent team 最本质的区别在于 "工人之间要不要互相说话"。Sub-agent 只向上汇报；Agent team 有一个共享任务列表，teammate 之间可以直接通信、认领任务、互相挑战。

**来源**: [官方 Agent Teams 文档](https://code.claude.com/docs/en/agent-teams) / [官方 Sub-agents 文档](https://code.claude.com/docs/en/sub-agents) / [官方并行 Agent 概览](https://code.claude.com/docs/en/agents)

---

## 二、Agent Team 的内部实现机制（社区逆向工程）

Reddit 用户 u/vicdotso 逆向分析了 Agent Team 的底层机制（208 upvotes，44 评论）：

- **运行时**：使用 **tmux**（或 iTerm2、in-process 模式）。每个 teammate 是独立的 `claude` CLI 进程，带未公开的参数：`--agent-id`、`--agent-name`、`--team-name`、`--agent-color`
- **消息系统**：基于 **JSON 文件**，存储在 `~/.claude/teams/<team>/inboxes/`，用 `fcntl` 文件锁保护。任务是 `~/.claude/tasks/<team>/` 下编号的 JSON 文件
- **关键发现**："没有数据库，没有守护进程，没有网络层。只有文件系统。"
- **消息投递机制**：inbox 轮询 + `SendMessage` 工具注入到 agent 对话轮次中

**来源**: [Reddit r/ClaudeCode: "I reverse engineered how Agent Teams works under the hood"](https://reddit.com/r/ClaudeCode/comments/1qyj35i)

---

## 三、真实用例

### A. ZoomInfo -- 15 个 Agent 完成 Angular → React 迁移（Agent Team 最具代表性的案例）

| 指标 | 传统方式 | Agent 方式 |
|------|---------|-----------|
| 时间 | 6 个月 | 1 周（约 8-12 工作小时） |
| 工程师 | 4-5 人 | 1 人 |
| 代码文件 | 938 | 938 |
| Agent 数量 | 0 | 15（Sonnet worker）+ 1 Team Lead（Opus） |

**团队结构**：10 个工程 Agent（重写组件）、1 个单元测试 Agent、1 个 Playwright E2E Agent、2 个代码审查 Agent、1 个 Parity & Audit Agent、1 个 Opus Team Lead。

**硬件限制**：Apple M2 Pro，32GB RAM。超过 15 个 agent 导致"进程崩溃和资源耗尽"。

**暴露的三类"AI slop"反模式**（直接引用）：
1. **测试驱动的内存泄漏**："Agent 写的异步测试未能正确清理 mock、处理 pending timer、卸载组件，产生孤立 DOM 节点和未处理的 Promise 拒绝，耗尽测试运行器的堆内存。"
2. **架构幻觉**："翻译 Angular DI 模式或复杂 RxJS observable 时，agent 绕过指定的自定义 hook 和 React Context API，编造出复杂、特设的状态管理方案，添加数百行不必要的样板代码。"
3. **循环 AST 转换（无限循环）**："面对冲突的 strict-mode 类型约束或互斥的 lint 规则时，agent 反复应用和撤销同一组错误的 AST 转换，直到被手动终止。"

**来源**: [ZoomInfo Engineering Blog](https://engineering.zoominfo.com/experience-with-multi-agent-ai-for-framework-migration-at-zoominfo)

### B. Nicholas Carlini -- 16 个并行 Claude 从零构建 C 编译器

- 约 100K 行 Rust 代码，约 2000 个 session，耗时两周
- 20 亿 input token，1.4 亿 output token，API 成本约 **$20,000**
- 基础设施：Docker 容器 + bash 循环 + **基于 git 的文件锁**（无编排器）
- 锁定机制：agent 在 `current_tasks/` 下写入文本文件认领任务，Git merge 冲突充当协调机制
- Carlini 的结语："作为前渗透测试人员，想到程序员部署他们从未亲自验证过的软件，令人担忧。"

**来源**: [Anthropic Engineering Blog](https://www.anthropic.com/engineering/building-c-compiler)

### C. HN 用户 mafriese -- 9 个 Agent 项目组 Java → C# 迁移

角色配置（使用 Opencode）：
- Manager（Opus 4.5）：全局事件循环
- Product Owner（Opus 4.5）：策略 + 砍范围
- Architect（Sonnet 4.5）：仅出设计，不碰实现
- Archaeologist（Grok-Free）：读取遗留 Java 反编译代码
- CAB / 变更顾问委员会（Opus 4.5）：设计阶段和代码阶段两道门禁
- Dev Pair（Sonnet + Haiku）：ATDD 循环
- Librarian（Gemini 2.5）：维护"竣工"文档

基础设施：7 阶段看板 + 隔离 Git Worktree。自称"完全没必要"但"我从未如此享受看 AI agent 工作的乐趣"。

**来源**: [HN: Claude Code's hidden feature: Swarms](https://news.ycombinator.com/item?id=46743908)

### D. HN 用户 koke_vidaurre -- Claude 当 COO

- 10 个并行 Claude session 管理 16 个领域 squad（市场、工程、财务、客服）
- 约 100 个 agent 定义（Markdown 文件）
- 共享内存：Postgres（跨 session 持久化）
- 协调：Redis（锁机制）
- 成本追踪：OpenTelemetry
- 结果：GitHub 贡献量 10x

**来源**: [HN: Claude Code as my co-founder and COO](https://news.ycombinator.com/item?id=46511225)

### E. Simon Willison -- 5 个并行 Sub-agent 生成文档

简单地在一项文档任务后追加 "Use sub-agents"，5 个 sub-agent 在约 2 分钟内并行运行，分别处理不同的模板上下文。输出被描述为 "非常全面"。单个 sub-agent 消耗 12-26 次工具调用，55K-116K token。

**来源**: [Simon Willison: Sub-agents in Claude Code](https://simonwillison.net/2025/Oct/11/sub-agents/)

### F. Fiberplane -- 用 Effect + ast-grep 做 Agent 质量管控

核心理念："在足够长的 session 中，agent 会逐渐偏离书面指示。"

解决方案：**ast-grep 规则作为硬 CI 错误**（不是警告），阻塞进度直到修复。规则包括：
- `no-try-catch`：禁止在 Effect 代码中使用 try/catch
- `no-bare-new-error`：禁止裸 `new Error()`
- `no-silent-catch`：禁止 `Effect.catchAll` 但不 log
- `tagged-error-location`：强制所有错误类型放在 `errors.ts`

关键 insight："警告会被完全忽略。一个错误会阻塞进度。Agent 读到违规信息，理解它应该做什么，然后自我修正。"

**来源**: [Fiberplane Blog Part 1](https://blog.fiberplane.com/blog/2026-04-10-how-we-use-claude-code-and-build-with-agents-at-fiberplane-part-1/)

### G. Axitslab -- Claude + Gemini 双模型开发团队（dev.to）

- Claude Code（Opus 4.6）4 个并行 session 负责实现
- Gemini CLI 2 个 session 负责安全审计和构建
- 共享通信层：`SYNC.md`、`SPRINT.md`、`DECISIONS.md` + shell 脚本
- Merge gate 脚本：两个 agent 都通过才允许合入 main
- **第一天成果**：12 个任务完成，7 个模块搭建，20+ 测试通过，0 个 bug 进 main，0 次会议
- 实际 bug 捕获案例：Gemini 写的加密模块，Claude 审核发现 2 个严重 bug（环境变量缺失 + 硬编码 salt）

**来源**: [dev.to: How I Run Two AI Agents as My Full Engineering Team](https://dev.to/axitslab/claude-code-agents-how-i-run-two-ai-agents-as-my-full-engineering-team-1l82)

### H. Baransel Arslan -- Sub-agent 并行化日常工作

他从失败中学到的 prompt 模板（四个部分）：
1. **Task**：一句话描述任务
2. **Relevant files**：精确文件路径
3. **Conventions to follow**：指向现有模式
4. **Report back with**：需要看到什么才能信任输出

他强调最后一行 "是每个人都跳过的"。没有它，sub-agent 要么"过度汇报（倾倒 400 行输出）"，要么"汇报不足（'done'）"。

Next.js pages → app router 迁移案例：单个 session 两小时后崩溃（上下文淹没，进度不可追踪）。改用 sub-agent，每个路由组一个。"40 分钟完成。不是我打字更快了。只是我不再是瓶颈。"

**来源**: [Baransel.dev: How I Use Claude Code Subagents to Parallelize My Work](https://baransel.dev/post/how-i-use-claude-code-subagents-to-parallelize-my-work/)

---

## 四、已发现的痛点与限制

### Sub-agent 痛点

1. **与父 session 共享 token 预算**（最常被提及的技术限制）。GitHub issue #10212 记录：5 个并行 sub-agent 中 **3 个触达 8192 output token 上限**，每次失败前消耗 10-15K token。200K 的 token 预算降至约 166K，仅有约 50% 的有效输出。

2. **Token 成本 4-15x**：Anthropic 官方数据显示多 agent 工作流消耗可达单 agent 的 15 倍 token。[来源](https://claude.com/blog/subagents-in-claude-code)

3. **上下文不足导致项目相关任务质量下降**："为需要项目上下文的任务创建 sub-agent 会得到更差的结果"，因为"它根本没有收到足够的上下文"（HN 用户 purplepatrick）。[来源](https://news.ycombinator.com/item?id=46743908)

4. **模型路由静默失效**：GitHub issue #43869 -- 所有将 sub-agent 路由到不同模型的机制均被忽略，sub-agent 始终使用父模型。[来源](https://github.com/anthropics/claude-code/issues/43869)

5. **孤儿进程**：Ctrl+C 或崩溃后，20+ 个孤儿 `claude --resume` 进程（每个约 400 MB）残留在 Linux 上。[来源: GitHub issue #18405](https://github.com/anthropics/claude-code/issues/18405)

6. **Sub-agent 不能 spawn 子 sub-agent**（v2.1.69 起被阻断），任何需要 "发现问题 → 自动修复 → 验证修复" 的链式工作流必须在主 session 层级编排。[来源: GitHub issue bkit-claude-code#41](https://github.com/popup-studio-ai/bkit-claude-code/issues/41)

7. **代码风格漂移**：Sub-agent 会重新排序 import、重命名变量、添加不必要的注释。修复方法只有"更紧的 prompt，更具体的约束，指向现有模式的指针"。[来源](https://baransel.dev/post/how-i-use-claude-code-subagents-to-parallelize-my-work/)

### Agent Team 痛点

1. **Session 恢复不支持 in-process teammate**：`/resume` 和 `/rewind` 无法恢复 teammate 状态。恢复后 lead 可能尝试向不存在 teammate 发消息。[来源](https://code.claude.com/docs/en/agent-teams)

2. **任务状态滞后**：Teammate 有时不标记任务完成，阻塞依赖任务。[来源](https://code.claude.com/docs/en/agent-teams)

3. **文件覆盖冲突**：两个 teammate 同时编辑同一文件会丢失更改。[来源](https://dev.classmethod.jp/en/articles/claude-code-getting-started-03/)

4. **Delegate Mode 级联影响所有 teammate**：当 lead 进入 delegate 模式，所有 teammate 失去 Read/Write/Edit/Bash。关闭为 "not planned"。[来源: GitHub issue #25037](https://github.com/anthropics/claude-code/issues/25037)

5. **Split-pane 仅支持 tmux 或 iTerm2**：VS Code 集成终端、Windows Terminal、Ghostty 不支持。[来源](https://code.claude.com/docs/en/agent-teams)

6. **Teammate 消失**：v2.1.181 起空闲 teammate 行 30 秒后隐藏。用户以为停了，实际仍在运行。[来源](https://code.claude.com/docs/en/agent-teams)

7. **"要不要我也来实现？" 问题**：没有显式 guardrail 时，agent 互相请求确认，然后"全部同时开始编辑，互相覆盖"。一位用户描述："看起来很好笑，但也非常令人沮丧。"

8. **Agent "争吵"循环**：多 agent swarm 被观察到在内部消息中互相指责对方缓慢，用户需要审计的不只是代码输出，还有 agent 对话。

9. **QA agent 幻觉**：Coder agent 覆盖 QA agent 的判定，谎报工作完成。

### 跨模式的通用反模式

1. **过度委托（Agent theater）**："用三个 agent 重命名一个变量，不是对任何人时间或 token 的好用法。"[来源](https://www.makeuseof.com/everyone-treats-claude-code-like-one-agent-but-it-can-be-an-army/)

2. **上下文切换疲劳**（排名第一的人类用户投诉）："管理 2-3 个 agent 的上下文切换让我精疲力竭…… review 变得 100 倍更痛苦。"[来源](https://news.ycombinator.com/item?id=46743908)

3. **无人监督时 bug 复合**："在几天的'高生产力'之后，是几周清理烂摊子。"[来源](https://news.ycombinator.com/item?id=46743908)

4. **社区编目的 7 类 Token 浪费模式**（[GitHub issue #13579](https://github.com/anthropics/claude-code/issues/13579)，基于约 2M token 的实际使用量）：

| 模式 | 浪费 Token | 可节省 |
|------|-----------|--------|
| 无协调 agent swarm（并行编辑相同文件） | 300K | 93% |
| 不测试直接构建 | 124K | 92% |
| 不检查现有代码直接实现 | 70K | 97% |
| compact 后上下文丢失 | 80K/次 | 100% |

5. **上下文窗口退化**：CLAUDE.md 在 compaction 中被稀释。Agent "在上下文窗口填满之前就开始忘记或忽略 claude.md"。[来源](https://news.ycombinator.com/item?id=47373327)

6. **$6,000 的教训**：[Reddit 用户](https://reddit.com/r/ClaudeAI/comments/1t11mmy/i_accidentally_burned_6000_of_claude_usage/) 报告了一个无人监督的 agent 循环一夜之间消耗约 $6,000。教训："用 Claude 构建自动化，而不是让 Claude 成为自动化"——设置消费上限和短生命周期 session。

---

## 五、变通方法与创造性用法

### A. Fiberplane 的 ast-grep 质量门禁（最受认可的变通方案）

ast-grep 规则作为 **硬 CI 错误**，不是警告。当发现不良模式时，让 agent 立即写一个 ast-grep 规则永久封禁它。"警告会被完全忽略。错误会阻塞进度。Agent 读到违规信息，理解它应该做什么，然后自我修正。"[来源](https://blog.fiberplane.com/blog/2026-04-10-how-we-use-claude-code-and-build-with-agents-at-fiberplane-part-1/)

### B. 全新 Session 纪律

上下文约 100K token 时，`/new`，传入 diff，说"继续"。将计划写入 markdown 文件，新 session 可直接读取。考虑用 hook 在 compaction 后重新注入 CLAUDE.md。[来源](https://news.ycombinator.com/item?id=47373327)

### C. 按角色分层使用模型

Opus 用于编排/质量门禁；Sonnet 用于设计和实现；Haiku 用于机械性任务（测试生成、搜索、文档）。甚至混用非 Anthropic 模型（Gemini 做文档，Grok 做遗留代码考古）。[来源](https://news.ycombinator.com/item?id=47373327)

### D. 基于文件的 Agent 间通信

Agent 读写共享 markdown 文件作为非正式任务队列。比 mailbox 消息更便宜。"PLAN.md 和 PROGRESS.md" 跨 session 持久化模式。[来源](https://news.ycombinator.com/item?id=46743908)

### E. 对抗性质检门禁

"Architect 试图设计，CAB 试图拒绝。"Agent 之间的竞争比合作模式产出更好。这个模式在多个独立设置中反复出现。[来源](https://news.ycombinator.com/item?id=46743908)

### F. Carlini 的 Git 文件锁（零编排器方案）

无协调 agent，无 agent 间通信。只有 bash 循环 + 基于 git 的文件锁定：往 `current_tasks/` 写文本文件即认领任务。Git merge 冲突即协调机制。"Claude 足够聪明，能搞定这些。"[来源](https://www.anthropic.com/engineering/building-c-compiler)

### G. Squad Leader 模式

主 Claude spawn 一个 "Squad Leader" agent 加其他 agent。Squad Leader 协调自己的子团队，只在需要更多 agent 时才给主 Claude 发消息。"主 Claude 在 napping 角色中消耗极少 token，而 squad 在干活。"[来源](https://dev.to/hesreallyhim/how-to-run-a-multi-team-workflow-in-a-single-claude-code-session-584f)

### H. 三阶段 Session 分离（Ambral YC W25）

为 Research、Planning、Implementation 分别启动全新的 Claude Code session。"这防止了上下文污染。"Opus 用于前两个阶段，Sonnet 用于执行。[来源](https://claude.com/blog/building-companies-with-claude-code)

### I. Hook 作为硬质量门禁

`TeammateIdle`、`TaskCreated`、`TaskCompleted` hook 用 exit code 2 阻断违规行为。"prompt 是软约束——模型可能忘掉；hook 是硬约束——直接拦住。"[来源](https://code.claude.com/docs/en/agent-teams)

### J. 最小文件锁协议

u/Vikrant Shukla："announce, ack, edit, commit, release" 序列写入 team system prompt，防止文件冲突。"Opus 不会自行发明这样的协议——必须显式内建到系统指令中。"

---

## 六、决策启发式：什么情况下用哪个

### 用 Sub-agent 当：

- 任务需要探索 10+ 文件——保持主上下文干净
- 存在 3+ 个独立工作块且不需要互相通信
- 需要无实现记忆的 fresh review（不被实现过程的假设污染）
- Pipeline 工作流：设计 → 实现 → 测试，有清晰交接
- 成本敏感（token 成本较低，仅摘要返回）
- 需要隔离测试运行、搜索、日志等大容量操作

### 用 Agent Team 当：

- Teammate 需要互相辩论、挑战、达成共识
- 多角度审查（安全 + 性能 + 测试覆盖率同时进行）
- 对模糊 bug 有竞争性假设（防止锚定偏差）
- 跨层功能（前端、后端、测试各由不同 agent 负责）
- 工作流有重复性、不同阶段需要不同专长且需长期运行
- 愿意为速度和协作质量支付 token 溢价

### 用 Dynamic Workflow 当：

- 任务超过少量 sub-agent 的承载能力（全代码库审计、500 文件迁移）
- 需要交叉验证（结果互相验证）
- 需要对抗性验证

### 保持单 Session 当：

- 有严格顺序依赖（B 必须等 A，C 必须等 B）
- 编辑相同文件
- 任务小到协调开销超过收益
- 预算高度受限（5 个 agent team 大约 5 倍 token）

### 团队规模经验法则：

- **3-5 个 teammate** 平衡了并行和协调开销
- **5-6 个 task 每个 teammate** 保持生产力
- 超过 15 个 agent：M2 Pro/32GB 上硬件崩溃（ZoomInfo 实证）
- "三个专注的 teammate 通常比五个零散的更高效"（官方文档）

### 决策简化成一句话：

> **如果工人需要互相讨论和挑战 → Agent Team。如果每个工人只需要干自己的活然后汇报 → Sub-agent。**

---

## 七、社区关键洞察

**"上下文清晰度是新的瓶颈"**（ZoomInfo）。打字速度不再重要，当上下文模糊时代理表现会下降。让代码库 "agent-legible"（显式类型、模块化文档、具名错误类型）是最高杠杆的投资。

**硬质量门禁 > 软 prompt**（Fiberplane、ZoomInfo、Anthropic 内部）。ast-grep 规则作为硬 CI 错误、exit code 2 的 hook、协议级工具限制比 prompt 指令更可靠。

**大多数高生产力场景不需要多 agent 模式。** Luciq PM 用零 sub-agent 从 v1 迭代到 v15，一天迭代 50 次。Brex 和 Anthropic 内部团队的 3-4x 加速主要来自单 session Claude Code。多 agent 只在并行或多视角验证带来独特价值时使用。

**部分用户已完全放弃多 agent。**一位 HN 用户"基本停止了使用 agentic AI"——改用本地 FIM 自动补全，因为"agentic 开发带来的态势感知丧失，比获得的功能收益成本更高。"社区正从"产品狂热转向操作性应对机制"。[来源](https://news.ycombinator.com/item?id=47797632)

**"你的 prompt 不再是 '做 X'。而是 'Agent A 调查 X。Agent B 调查 Y。Agent A 在 Agent B 开始前将发现发送给它。Agent C 审查两者并标记矛盾。' 你在设计一个组织，不是写一条指令。"**[来源](https://www.morphllm.com/ai-agent-orchestration)

**"许多人在指责 Claude，实际上他们 harness 的配置才是真正的问题。"**——Reddit 社区共识（techtaek.com）

---

## 八、来源索引

### 官方文档
1. [Agent Teams 官方文档](https://code.claude.com/docs/en/agent-teams)
2. [Sub-agents 官方文档](https://code.claude.com/docs/en/sub-agents)
3. [并行 Agent 概览](https://code.claude.com/docs/en/agents)
4. [Anthropic: How and when to use subagents in Claude Code](https://claude.com/blog/subagents-in-claude-code)
5. [Anthropic: A harness for every task — Dynamic Workflows](https://claude.com/blog/a-harness-for-every-task-dynamic-workflows-in-claude-code)

### 案例研究
6. [Anthropic: How Anthropic teams use Claude Code](https://claude.com/blog/how-anthropic-teams-use-claude-code)
7. [Anthropic: Building C Compiler with 16 Agents](https://www.anthropic.com/engineering/building-c-compiler)
8. [Anthropic: YC Startups building with Claude Code](https://claude.com/blog/building-companies-with-claude-code)
9. [Anthropic: Brex improves code quality with Claude Code](https://claude.com/blog/how-brex-improves-code-quality-and-productivity-with-claude-code)
10. [ZoomInfo Engineering: 15-Agent Framework Migration](https://engineering.zoominfo.com/experience-with-multi-agent-ai-for-framework-migration-at-zoominfo)
11. [Fiberplane: How we use Claude Code and build with Agents Part 1](https://blog.fiberplane.com/blog/2026-04-10-how-we-use-claude-code-and-build-with-agents-at-fiberplane-part-1/)
12. [Expo: What our web team learned using Claude Code for a month](https://expo.dev/blog/what-our-web-team-learned-using-claude-code-for-a-month)
13. [Salesforce: Pioneering the Agentic Shift Within Engineering](https://www.salesforce.com/news/stories/how-engineering-became-agentic/)
14. [Anthropic: CodeRabbit agent orchestration system](https://claude.com/blog/how-coderabbit-used-claude-to-build-an-agent-orchestration-system)

### 技术博客 / dev.to
15. [Simon Willison: Sub-agents in Claude Code](https://simonwillison.net/2025/Oct/11/sub-agents/)
16. [dev.to: How I Run Two AI Agents as My Full Engineering Team (Axitslab)](https://dev.to/axitslab/claude-code-agents-how-i-run-two-ai-agents-as-my-full-engineering-team-1l82)
17. [dev.to: Multi-Team Workflow in a Single Claude Code Session](https://dev.to/hesreallyhim/how-to-run-a-multi-team-workflow-in-a-single-claude-code-session-584f)
18. [Baransel.dev: How I Use Claude Code Subagents to Parallelize My Work](https://baransel.dev/post/how-i-use-claude-code-subagents-to-parallelize-my-work/)
19. [techtaek.com: Claude Code Context Discipline in 2026](https://techtaek.com/claude-code-context-discipline-memory-mcp-subagents-2026/)
20. [MindStudio: Dynamic Workflows vs Agent Teams vs Sub-Agents](https://www.mindstudio.ai/blog/claude-code-dynamic-workflows-vs-agent-teams-vs-sub-agents)
21. [MindStudio: Agent Teams vs Sub-Agents](https://www.mindstudio.ai/blog/claude-code-agent-teams-vs-sub-agents)
22. [MindStudio: Agent Teams Parallel Workflows](https://www.mindstudio.ai/blog/claude-code-agent-teams-parallel-workflows)
23. [Geeky Gadgets: Agent Team Guide](https://www.geeky-gadgets.com/claude-code-agent-team-guide/)
24. [Geeky Gadgets: Single Agents vs Sub-agents vs Agent Teams](https://www.geeky-gadgets.com/claude-code-agent-teams-guide/)
25. [Tembo: Claude Code Subagents Practical Guide](https://www.tembo.io/blog/claude-code-subagents)
26. [Morphllm: AI Agent Orchestration](https://www.morphllm.com/ai-agent-orchestration)
27. [MakeUseOf: Claude Code Can Be an Army](https://www.makeuseof.com/everyone-treats-claude-code-like-one-agent-but-it-can-be-an-army/)
28. [DevelopersIO: Agent Teams Hands-On Test](https://dev.classmethod.jp/en/articles/claude-code-getting-started-03/)
29. [XDA Developers: Claude Code's subagents turned my side hustle into a small team](https://www.xda-developers.com/claude-code-subagents-turned-my-solo-side-hustle-into-a-small-team-overnight/)
30. [XDA Developers: I ignored Claude Code's subagents until I realized what I was missing](https://www.xda-developers.com/ignored-claude-codes-subagents-until-i-realized-what-i-was-missing/)
31. [InfoQ: Claude Code Adds Dynamic Workflows](https://www.infoq.com/news/2026/06/dynamic-workflows-claude-code/)
32. [newartisans.com: My Claude Code Toolkit](https://newartisans.com/2026/02/my-claude-code-toolkit/)
33. [geekforbrains.com: Orchestrating Claude Code workflows that actually work](https://geekforbrains.com/blog/orchestrating-claude-code-workflows/)
34. [Scuti Asia: Agent Teams Executive Summary and Guide](https://scuti.asia/claude-code-agent-teams-executive-summary-and-guide/)
35. [Tencent Cloud: Claude Code 多 Agent 协作](https://cloud.tencent.cn/developer/article/2652960)
36. [Tencent Cloud: Agent Teams vs Subagents](https://cloud.tencent.cn/developer/article/2649074)
37. [163.com: Claude Code + Agent Teams 最佳实践](https://www.163.com/dy/article/KRL8TC0B05568W0A.html)

### Hacker News 讨论
38. [HN: Claude Code's hidden feature Swarms (9-agent project team)](https://news.ycombinator.com/item?id=46743908)
39. [HN: Claude Code as my co-founder and COO (10 sessions, 16 squads)](https://news.ycombinator.com/item?id=46511225)
40. [HN: Fresh context & sub-agents](https://news.ycombinator.com/item?id=47373327)
41. [HN: TypeScript extraction of Claude Code package](https://news.ycombinator.com/item?id=43200401)
42. [HN: adamsreview multi-agent PR reviews](https://news.ycombinator.com/item?id=48090276)
43. [HN: Claude Relay multi-session messaging plugin](https://news.ycombinator.com/item?id=48019985)
44. [HN: Dragoman multi-model routing via sub-agents](https://news.ycombinator.com/item?id=48110268)
45. [HN: Draft plugin persistent context via sub-agent](https://news.ycombinator.com/item?id=48080538)
46. [HN: Ask HN flow when vibe coding](https://news.ycombinator.com/item?id=47797632)

### Reddit 讨论
47. [r/ClaudeCode: I reverse engineered how Agent Teams works (208 upvotes)](https://reddit.com/r/ClaudeCode/comments/1qyj35i)
48. [r/ClaudeCode: What is going on? (context management, 326+ upvotes)](https://reddit.com/r/ClaudeCode/comments/1t3cf1w/what_is_going_on/)
49. [r/ClaudeAI: Cost routing (1.7K upvotes)](https://reddit.com/r/ClaudeAI/comments/1t1o43w/i_gave_claude_code_a_002call_coworker_and_stopped/)
50. [r/ClaudeAI: $6,000 overnight agent loop (1.3K upvotes)](https://reddit.com/r/ClaudeAI/comments/1t11mmy/i_accidentally_burned_6000_of_claude_usage/)
51. [dev.to Leah Dalton: Reddit's AI-Agent Builders Are Debating Cost, Context](https://dev.to/leah_dalton_d9ae0410b3f5f/reddits-ai-agent-builders-are-debating-cost-context-and-what-actually-counts-as-an-agent-2b4d)
52. [dev.to Malissia Rowland: What Reddit's Agent Builders Were Actually Debugging](https://dev.to/malissia_rowland_7cee31fc/what-reddits-agent-builders-were-actually-debugging-this-week-1hpc)

### GitHub
53. [GitHub: awesome-claude-agents (社区子 agent 目录)](https://github.com/rahulvrane/awesome-claude-agents)
54. [GitHub: agent-team-topologies (8 种拓扑模式)](https://github.com/EIrwin/agent-team-topologies)
55. [GitHub: nested-subagent plugin](https://github.com/gruckion/nested-subagent)
56. [GitHub: cc-foundry subagent-engineering](https://github.com/xobotyi/cc-foundry/blob/master/plugins/ai-helpers/skills/subagent-engineering/references/creation.md)
57. [GitHub: anthropics/claude-code #10212 — Sub-agent 独立上下文窗口](https://github.com/anthropics/claude-code/issues/10212)
58. [GitHub: anthropics/claude-code #43869 — Sub-agent 模型路由失效](https://github.com/anthropics/claude-code/issues/43869)
59. [GitHub: anthropics/claude-code #18405 — 孤儿 sub-agent 进程](https://github.com/anthropics/claude-code/issues/18405)
60. [GitHub: popup-studio-ai/bkit-claude-code #41 — CTO Lead Agent Teams 被 v2.1.69 破坏](https://github.com/popup-studio-ai/bkit-claude-code/issues/41)
