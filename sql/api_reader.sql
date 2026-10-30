-- Read-only role for the public API. Run once in the Neon SQL editor, connected as the
-- database owner (the role in DATABASE_URL), after replacing the password.
-- Then set API_DATABASE_URL to the same connection string as DATABASE_URL, but with
-- api_reader and this password as the user and password.

CREATE ROLE api_reader WITH LOGIN PASSWORD 'replace-with-a-long-random-password';

GRANT CONNECT ON DATABASE neondb TO api_reader;   -- your database name, if not neondb
GRANT USAGE ON SCHEMA public TO api_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO api_reader;

-- Tables the pipeline creates later (create_all) are readable too.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO api_reader;

-- Check: as api_reader, this works...
--   SELECT count(*) FROM postings;
-- ...and this fails with "permission denied":
--   DELETE FROM postings WHERE false;
