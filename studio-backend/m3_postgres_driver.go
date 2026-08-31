package main

// Register pgx with database/sql. Cloud SQL for PostgreSQL and the local
// PostgreSQL verification database both use this driver; repository callers
// open the connection with sql.Open("pgx", dsn).
import _ "github.com/jackc/pgx/v5/stdlib"
