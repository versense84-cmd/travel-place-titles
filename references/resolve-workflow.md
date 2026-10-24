# Resolve 适配与执行

## 两种连接方式

- AI 已连接 Resolve MCP：查询当前版本的脚本 API，用连接器取得当前 Resolve/Project 对象。通过允许本地文件读取的工具导入 `scripts/resolve_places.py`，调用其函数；不要把文件读操作伪装成无系统访问的沙箱脚本。没有文件读取能力时，基于该脚本适配所需函数即可。
- 本地 Python：配置达芬奇官方 `DaVinciResolveScript` 模块和运行库，`api.scriptapp('Resolve')` 必须能连接。模块位置、应用设置和版本限制依本机官方 Scripting 文档。Skill 不会自动安装或开放达芬奇的脚本接口。

## 最短本地流程

```bash
python3 scripts/resolve_places.py inspect --tracks 1,2 --out work
python3 scripts/resolve_places.py capture --plan work/plan.json --out work/frames
# AI查看帧并联网查证，填写work/plan.json中的cn/en/confidence/evidence/sources。
python3 scripts/resolve_places.py validate --plan work/plan.json
python3 scripts/make_carrier.py --snapshot work/snapshot.json --plan work/plan.json --out work/title-carrier.mov
python3 scripts/resolve_places.py apply --plan work/plan.json --carrier work/title-carrier.mov --chinese-font 'PingFang SC' --english-font 'Helvetica Neue' --apply
```

轨道号和字体是示例，必须改成本机实际选择。应用后用新的脚本调用回读标题轨道，并提取合成帧验证；`apply` 的函数内回读不替代保存后的独立检查。

## 可供其他客户端使用的函数

```python
snap = snapshot(project)
plan = make_plan(snap, [1, 2])
# 查看合成帧和网页证据后填写 plan。
rows = validate_plan(plan, snapshot(project))
summary = apply_titles(resolve, plan, carrier_path, chinese_font, english_font)
```

`footage_tracks` 必须排除不作为地点依据的参考视频、透明边框和旧标题。`segments` 只提出最高实拍轨的候选区间，不解析透明度、转场或复合剪辑。此类复杂镜头由AI查看实际合成画面后决定范围，不能把候选清单当自动识别结果。

`capture` 为保守实现，仅转换整数帧率的非丢帧时间码；分数帧率、丢帧或特殊起始时间码用当前连接器或UI核对定位。写入器可接收分数帧率，但载体必须具有相同帧率和足够帧数。

## 标题载体和端点

使用透明视频作为载体而不是 PNG。实践中仍图 `AppendToTimeline` 可能采用默认仍图时长，忽略请求范围。脚本写入后检查真实起止，不匹配立即停止。当前实现使用已在 Resolve Studio 21.1.1 验证过的 `endFrame = duration` 方式；其他版本若端点约定不同，需按实际API调整后再写入。

标题是两层Fusion Text+，合并到MediaOut，不使用原素材作为输出。可编辑、可关闭，但项目仍引用载体文件。不要删除工作目录里的MOV。API并不保证所有版本字体和阴影表现一致，必须查看实际画面。字体缺失时用户应选择本机可用字体，不自动下载商业字体。

失败可能留下部分新增轨道。停止并报告备份名与新增轨道号；恢复或移除仅限本次明确识别的新增项。已有生成轨道默认拒绝再叠加；修改旧标题时应重新核对底层素材并针对性更新，不清空用户轨道。
