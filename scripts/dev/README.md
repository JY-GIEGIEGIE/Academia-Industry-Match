# scripts/dev

S-12 开发库与演示种子脚本。完整说明见
`docs/09-项目管理/开发库与部署说明_2026-11-25.md`。

```bash
# 1. 建 s2_mvp_20261125 并导入 v0.1.2
./.venv/Scripts/python.exe scripts/dev/create_dev_db.py --zip "D:/path/to/S-08_v0.1.2_2026-11-23.zip"

# 2. 两个演示账号（S-13 给出记录 ID 后再加 --achievement-id/--demand-id）
./.venv/Scripts/python.exe scripts/dev/seed_demo.py

# 当前临时绑定；S-13 正式 ID 到后用同一命令覆盖（会自动清旧绑定）
./.venv/Scripts/python.exe scripts/dev/seed_demo.py \
  --achievement-id ach_openalex_W4200428349 --demand-id dem_005

# 解绑演示记录（只清 publisher_user_id / published_at）
./.venv/Scripts/python.exe scripts/dev/seed_demo.py \
  --unbind --achievement-id ach_xxx --demand-id dem_xxx

# 3. 计数检查（要求两个账号、1/1 绑定）
./.venv/Scripts/python.exe scripts/dev/check_dev_db.py --require-binding \
  --expect-achievement-id ach_openalex_W4200428349 --expect-demand-id dem_005
```

- 默认从仓库 `.env` 的 `DATABASE_URL` 派生连接，只替换库名。
- 写库脚本默认只允许 `s2_mvp_*`；其他库会被拒绝（`--allow-non-dev` 可覆盖，不建议）。
- `--recreate` 会删开发库，仅限 `s2_mvp_*` 使用。
- 验收库 `s08_v012_20261123` 不要写入。
