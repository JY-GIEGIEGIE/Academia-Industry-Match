-- 仅在数据库 volume 首次初始化时执行。
-- 表结构、索引和迁移由 BE2（张小桐）的 migrations/ 负责，这里只装扩展。
CREATE EXTENSION IF NOT EXISTS vector;
