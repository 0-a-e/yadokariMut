"""agent 支援モジュールパッケージ。

- checkpointer: LangGraph チェックポイント (AsyncPostgresSaver) の共有管理
- patches:      DeepSeek reasoning_content 連携の monkey-patch (明示適用)

本体の graph 生成は src/agent_service.py。web 層 (src/web/) から利用される。
"""
