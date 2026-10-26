-- All tenant policies fail closed without transaction-scoped context.
-- engine/db.py sets app.organization_id, app.user_id for memory, and the
-- api_key_hash only during key lookup via PostgreSQL SET LOCAL.
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'agents', 'skills', 'tasks', 'task_runs', 'approvals',
    'usage_costs', 'schedules', 'event_triggers', 'audit_log'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I', t || '_org_iso', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING
        (organization_id = NULLIF(current_setting(''app.organization_id'', true), ''''))
       WITH CHECK
        (organization_id = NULLIF(current_setting(''app.organization_id'', true), ''''))',
      t
    );
  END LOOP;

  ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
  ALTER TABLE api_keys FORCE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS tenant_isolation ON api_keys;
  DROP POLICY IF EXISTS api_keys_org_iso ON api_keys;
  CREATE POLICY tenant_isolation ON api_keys
    USING (
      organization_id = NULLIF(current_setting('app.organization_id', true), '')
      OR (key_hash = NULLIF(current_setting('app.api_key_hash', true), '')
          AND revoked_at IS NULL)
    )
    WITH CHECK (
      organization_id = NULLIF(current_setting('app.organization_id', true), '')
    );

  ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
  ALTER TABLE conversations FORCE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS owner_memory ON conversations;
  DROP POLICY IF EXISTS conversations_owner_memory ON conversations;
  DROP POLICY IF EXISTS conversations_org_iso ON conversations;
  CREATE POLICY owner_memory ON conversations
    USING (
      organization_id = NULLIF(current_setting('app.organization_id', true), '')
      AND owner_user_id = NULLIF(current_setting('app.user_id', true), '')
    )
    WITH CHECK (
      organization_id = NULLIF(current_setting('app.organization_id', true), '')
      AND owner_user_id = NULLIF(current_setting('app.user_id', true), '')
    );

  ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
  ALTER TABLE messages FORCE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS owner_memory ON messages;
  DROP POLICY IF EXISTS messages_org_iso ON messages;
  CREATE POLICY owner_memory ON messages
    USING (EXISTS (
      SELECT 1 FROM conversations c WHERE c.id = conversation_id
        AND c.organization_id = NULLIF(current_setting('app.organization_id', true), '')
        AND c.owner_user_id = NULLIF(current_setting('app.user_id', true), '')
    ))
    WITH CHECK (EXISTS (
      SELECT 1 FROM conversations c WHERE c.id = conversation_id
        AND c.organization_id = NULLIF(current_setting('app.organization_id', true), '')
        AND c.owner_user_id = NULLIF(current_setting('app.user_id', true), '')
    ));

  ALTER TABLE agent_versions ENABLE ROW LEVEL SECURITY;
  ALTER TABLE agent_versions FORCE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS tenant_isolation ON agent_versions;
  DROP POLICY IF EXISTS agent_versions_org_iso ON agent_versions;
  CREATE POLICY tenant_isolation ON agent_versions
    USING (EXISTS (
      SELECT 1 FROM agents a WHERE a.id = agent_id
        AND a.organization_id = NULLIF(current_setting('app.organization_id', true), '')
    ))
    WITH CHECK (EXISTS (
      SELECT 1 FROM agents a WHERE a.id = agent_id
        AND a.organization_id = NULLIF(current_setting('app.organization_id', true), '')
    ));

  ALTER TABLE skill_versions ENABLE ROW LEVEL SECURITY;
  ALTER TABLE skill_versions FORCE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS tenant_isolation ON skill_versions;
  DROP POLICY IF EXISTS skill_versions_org_iso ON skill_versions;
  CREATE POLICY tenant_isolation ON skill_versions
    USING (EXISTS (
      SELECT 1 FROM skills s WHERE s.id = skill_id
        AND s.organization_id = NULLIF(current_setting('app.organization_id', true), '')
    ))
    WITH CHECK (EXISTS (
      SELECT 1 FROM skills s WHERE s.id = skill_id
        AND s.organization_id = NULLIF(current_setting('app.organization_id', true), '')
    ));
END $$;
