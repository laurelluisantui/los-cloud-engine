-- Postgres-only: organization isolation via Row Level Security.
-- Apply once on the deployed database (Alembic migration 0001 must run first):
--   psql "$DATABASE_URL" -f db/migrations/0002_rls.sql
-- The engine connects with a role that sets app.organization_id per request;
-- direct table access without the GUC sees nothing.

DO $$
DECLARE
  t TEXT;
  org_scoped TEXT[] := ARRAY[
    'api_keys', 'agents', 'agent_versions', 'skills', 'skill_versions',
    'tasks', 'task_runs', 'approvals', 'conversations', 'messages',
    'usage_costs', 'schedules', 'event_triggers'
  ];
BEGIN
  FOREACH t IN ARRAY org_scoped LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY;', t);
    IF t = 'messages' THEN
      EXECUTE format(
        'CREATE POLICY messages_org_iso ON %I USING (conversation_id IN ('
        'SELECT id FROM conversations WHERE organization_id = '
        'coalesce(nullif(current_setting(''app.organization_id'', true), '''')::text, organization_id)));', t);
    ELSIF t = 'agent_versions' THEN
      EXECUTE format(
        'CREATE POLICY agent_versions_org_iso ON %I USING (agent_id IN ('
        'SELECT id FROM agents WHERE organization_id = '
        'coalesce(nullif(current_setting(''app.organization_id'', true), '''')::text, organization_id)));', t);
    ELSIF t = 'skill_versions' THEN
      EXECUTE format(
        'CREATE POLICY skill_versions_org_iso ON %I USING (skill_id IN ('
        'SELECT id FROM skills WHERE organization_id = '
        'coalesce(nullif(current_setting(''app.organization_id'', true), '''')::text, organization_id)));', t);
    ELSE
      EXECUTE format(
        'CREATE POLICY %I_org_iso ON %I USING (organization_id = '
        'coalesce(nullif(current_setting(''app.organization_id'', true), '''')::text, organization_id));',
        t, t);
    END IF;
  END LOOP;
END $$;

-- Audit log is append-only visible to the org's own rows.
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_log_org_iso ON audit_log
  USING (organization_id = coalesce(nullif(current_setting('app.organization_id', true), '')::text, organization_id));

-- conversations: additionally enforce owner-only reads for Muffy memory.
CREATE POLICY conversations_owner_memory ON conversations
  USING (owner_user_id = coalesce(nullif(current_setting('app.user_id', true), '')::text, owner_user_id)
         AND organization_id = coalesce(nullif(current_setting('app.organization_id', true), '')::text, organization_id));
