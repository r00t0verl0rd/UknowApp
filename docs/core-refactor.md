# Backend core boundaries

The backend core now only owns infrastructure primitives: settings, SQLAlchemy
engine/session setup, and stateless password/origin security helpers.

- `app.migrations.initialize_database()` registers models, creates missing tables,
  applies versioned compatibility migrations once, and performs startup retention
  maintenance. `schema_migrations` records completed upgrades in the database.
- Historical SQLite schema/data transforms live in `app.migrations.legacy`.
  The indexed `users.web_login_key` is populated in a separate migration, and
  ORM user writes keep it synchronized with Unicode `casefold()` normalization.
  Both login and uniqueness checks use the indexed key; duplicate keys remain
  non-unique at the database level to preserve historical login behavior.
- `app.modules.auth.service` owns authentication and session persistence;
  `app.core.security` no longer loads domain models or application rate limiters.
- `app.modules.notifications.vapid` manages key generation and loading explicitly.
  Startup loads keys after any pending full-data restore, and restore rollback also
  reloads the correct key material. Importing config alone does not create VAPID keys.
- Historical migration SQL contains SQLite-specific PRAGMAs and table rebuilds.
  Existing installations using PostgreSQL need database-specific upgrade planning;
  new PostgreSQL databases are created from SQLAlchemy metadata.

When adding a future schema change, add a new versioned migration before relying on
the new mapped column at runtime. Do not edit previously applied migration versions.
