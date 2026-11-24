# 活动转化归因复盘 · 实验放量判定单

工作台包含两块相互独立的账本：

1. **活动转化归因复盘**（<http://localhost:18309/>）：对已授权触点按 event-time 窗口做末次非直达归因，
   判断差异，签发合格批次或记录暂缓意见。
2. **实验放量判定单**（<http://localhost:18309/experiments>）：增长与财务联合复核。样本成熟且同周期对照匹配时，
   按退款净额增量正负给出继续/观察/回滚；未成熟但暂显优势的组不提前放量；重复来源或跨组重叠挡住整组发布；
   晚到更新只重算受影响组，回滚原子切换并保留全部旧版证据。

## 启动

```sh
docker compose up --build -d --wait
```

## 核验

```sh
docker compose exec -T app pytest -q
```

[输入字段](docs/DATA-DICTIONARY.md) · [阶段接口](docs/HTTP.md) · [操作步骤](docs/OPERATIONS.md) ·
[规则与测试](docs/DEPTH.md) · [放量判定口径](docs/EXPERIMENTS.md)
