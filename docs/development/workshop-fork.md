# 保留工坊的 fork 维护说明

本 fork 在上游 v3.7.19（`ad251fbdd25a4908dbf72dea3d8d34a15efc661e`）基础上恢复“角色工坊”。左侧进入该页面后，可以编辑、导入和导出队伍代码，再通过工坊按钮浏览公共配置。目录与 ZIP 来自原工坊仓库 [ok-oldking/ok-ww-char-code](https://github.com/ok-oldking/ok-ww-char-code)。

## 实现与使用

- `config.py` 通过原生 `custom_tabs` 注册 `src.gui.TeamWorkshopTab.TeamWorkshopTab`。
- `src/gui/TeamWorkshopTab.py` 迁入本地恢复插件的适配逻辑，继承上游 `CharacterCodeTab`。目录直接读取 GitHub Raw；ZIP 地址只由固定仓库和校验后的文件名生成。
- 上游队伍编辑、ZIP 大小限制、压缩包检查与导入确认流程继续复用；打开页面不会自动导入队伍。
- 未增加运行依赖。按照[贡献指南](contributing.md)安装依赖后，在此 fork 的源码目录运行 `py -3.12 main_debug.py`，左侧应出现“角色工坊”。打开工坊可搜索配置，取消导入应保留原队伍内容。

如果迁移到此 fork 的运行目录前已安装 `ok_import/local_team_workshop` 插件，先退出程序并将该插件移到备份目录，避免同一功能出现两个入口。不要删除用户 `configs`。

**源码 PR 不会切换已安装程序的更新源。** 当前 `pyappify.yml` 的 China / Global 仍指向官方发行更新仓库，直接使用官方启动器更新会继续运行官方代码。本 PR 提供源码维护方案；尚未建立本 fork 的独立发行仓库、安装包与自动更新渠道。原有官方安装及本地恢复插件可以继续使用。

## 选择性引入上游更新

`master` 维护本 fork 的可用版本，由维护者决定保留和调整哪些功能。原项目发布新版本后，先阅读版本说明与提交差异，选定需要的更新，再从本 fork 创建更新分支，向 **本 fork** 提 PR。默认按需移植，不自动跟随上游版本，也不使用上游分支强制覆盖 `master`。

以下 PowerShell 命令假设 `origin` 指向 `StreamLogic-lab553/ok-wuthering-waves`、`upstream` 指向 `ok-oldking/ok-wuthering-waves`；如未配置后者，先运行 `git remote add upstream https://github.com/ok-oldking/ok-wuthering-waves.git`。从干净工作区开始，每条命令成功后再继续：

```powershell
git fetch origin
git fetch upstream
git switch master
git merge --ff-only origin/master
git switch -c codex/pick-upstream-YYYYMMDD
git log --oneline master..upstream/master
git show <选定的提交SHA>
git cherry-pick -x <选定的提交SHA>
```

将尖括号占位符替换为实际提交 SHA，再执行对应命令。逐个检查所选提交的前置依赖，按依赖顺序引入；提交已被 cherry-pick 后会获得新 SHA，`master..upstream/master` 仍可能列出原提交，应结合 `git cherry -v master upstream/master` 与实际代码差异避免重复引入。一个提交混合多个功能或依赖过多时，手动移植需要的部分并记录原提交 SHA，再正常提交。只有明确决定接受上游全部未合入改动时，才使用 `git merge --no-ff upstream/master`。

发生冲突时先解决，不要直接采用整份上游文件。特别核对 `config.py` 中工坊注册、`CharacterCodeTab` 与 `CustomCharLoader` 的接口、Qt / ok-script 依赖变更。保留注册但底层模块已被删除也会失效，必须移植缺失实现或重新适配后才能合并。

```powershell
py -3.12 -u run_test.py tests.TestTeamWorkshopTab tests.TestCustomCharLoader
git push -u origin HEAD
gh pr create --repo StreamLogic-lab553/ok-wuthering-waves --base master
```

每次还应运行所选更新影响模块的测试，并在 PR 中列出引入的上游提交、相关依赖和验证结果。新增的 **Workshop compatibility** Actions 工作流会检查工坊注册、页面构造、目录处理、ZIP 导入确认及上游队伍代码回归。工作流只做检查，不自动同步或合并；首次在 fork 使用时，如 Actions 被禁用，需要在仓库 Actions 页面启用。

专用检查复用上游工坊行为测试，并运行完整队伍加载测试；既有 **Run Tests** 工作流继续运行全量测试。基线 v3.7.19 的 `test_team_state_dot_is_level_with_the_team_name` 在本地和 Windows CI 均出现 1 px 字体对齐差异（要求 ≤ 0.5 px），已在恢复 PR 记录；本改动保留其实现与断言，不将字体像素检查加入工坊专用套件。

测试通过后，用临时配置启动并检查入口、浏览目录、取消导入和确认导入，再合并同步 PR。检查失败时先修复兼容性，不要为通过检查而移除工坊注册或跳过测试。CI 是兼容性信号，不保证未来任意上游版本都能直接合并。
