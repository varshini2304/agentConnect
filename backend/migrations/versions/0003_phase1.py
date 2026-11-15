"""Frozen company foundation and explicit legacy ownership conversion."""
from datetime import datetime, timezone
import json

from alembic import context, op
import sqlalchemy as sa

revision = '0003_phase1'
down_revision = '0002_phase2'
branch_labels = None
depends_on = None


def create_foundation_tables():
    op.create_table('login_rate_limits',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('permissions',
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('description', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('company_roles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('is_builtin', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'slug'),
    sa.UniqueConstraint('id', 'company_id')
    )
    op.create_index(op.f('ix_company_roles_company_id'), 'company_roles', ['company_id'], unique=False)
    op.create_table('company_settings',
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('website', sa.String(length=2000), nullable=False),
    sa.Column('industry', sa.String(length=120), nullable=False),
    sa.Column('onboarding_complete', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('company_id')
    )
    op.create_table('company_invitations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('role_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['role_id', 'company_id'], ['company_roles.id', 'company_roles.company_id'], name='fk_invitation_company_role'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index('ix_company_invitation_email_status', 'company_invitations', ['company_id', 'email', 'status'], unique=False)
    op.create_index(op.f('ix_company_invitations_company_id'), 'company_invitations', ['company_id'], unique=False)
    op.create_table('role_permission_grants',
    sa.Column('role_id', sa.Integer(), nullable=False),
    sa.Column('permission_key', sa.String(length=80), nullable=False),
    sa.ForeignKeyConstraint(['permission_key'], ['permissions.key'], ),
    sa.ForeignKeyConstraint(['role_id'], ['company_roles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('role_id', 'permission_key')
    )

LEGACY_CONFIG_DEFAULTS = {'avatar': '🤖',
 'responsibilities': [],
 'helps_with': [],
 'must_not_do': [],
 'expected_outcomes': [],
 'topics': [],
 'partner_company_ids': [],
 'blocked_company_ids': [],
 'discoverable': False,
 'tone': 'professional',
 'response_preferences': 'concise',
 'allow_public': False,
 'allow_direct': False,
 'allow_group': False,
 'discussion_topics': [],
 'approval_topics': [],
 'allowed_actions': ['reply', 'skip', 'request_approval', 'end_conversation'],
 'allowed_publishing_categories': [],
 'require_approval': False,
 'limits': {'max_agent_messages': 3,
            'max_conversation_messages': 12,
            'max_reply_depth': 6,
            'max_participants': 8,
            'max_concurrent_runs': 2,
            'max_retries': 3,
            'timeout_seconds': 30,
            'cooldown_seconds': 30,
            'daily_runs': 100},
 'provider': 'fake',
 'model': 'legacy-preserved',
 'temperature': 0.2,
 'max_output_tokens': 500,
 'knowledge_source_ids': []}

PERMISSIONS = (
    'company.read', 'company.update', 'settings.manage', 'members.read',
    'members.manage', 'invitations.manage', 'roles.read', 'roles.manage',
    'agents.read', 'agents.manage', 'knowledge.read', 'knowledge.manage',
    'posts.read', 'posts.publish', 'workflow.run', 'discovery.read',
    'conversations.read', 'conversations.manage', 'approvals.manage',
)
ROLES = {
    'owner': PERMISSIONS,
    'admin': tuple(key for key in PERMISSIONS if key != 'roles.manage'),
    'operator': ('company.read', 'members.read', 'roles.read', 'agents.read', 'agents.manage', 'knowledge.read', 'knowledge.manage', 'posts.read', 'workflow.run', 'discovery.read', 'conversations.read', 'conversations.manage', 'approvals.manage'),
    'publisher': ('company.read', 'members.read', 'roles.read', 'agents.read', 'knowledge.read', 'posts.read', 'posts.publish', 'discovery.read', 'conversations.read'),
    'viewer': ('company.read', 'members.read', 'roles.read', 'agents.read', 'knowledge.read', 'posts.read', 'discovery.read', 'conversations.read'),
}


def upgrade():
    db = op.get_bind()
    now = datetime.now(timezone.utc).isoformat()
    defaults = lambda value: sa.text("'" + value.replace("'", "''") + "'")
    # SQLite can add nullable references without rebuilding historical parent tables.
    for table in ('agents', 'posts', 'notifications', 'routing_decisions', 'agent_interactions', 'comments'):
        op.execute(sa.text(f'ALTER TABLE {table} ADD COLUMN company_id INTEGER REFERENCES companies(id)'))
        op.create_index(f'ix_{table}_company_id', table, ['company_id'])
    op.add_column('companies', sa.Column('slug', sa.String(100), nullable=False, server_default=''))
    op.add_column('companies', sa.Column('status', sa.String(16), nullable=False, server_default='active'))
    op.add_column('companies', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=defaults(now)))
    db.execute(sa.text("UPDATE companies SET slug='company-' || id, updated_at=created_at"))
    op.create_index('uq_companies_slug', 'companies', ['slug'], unique=True)
    op.create_index('ix_companies_status', 'companies', ['status'])
    op.add_column('users', sa.Column('status', sa.String(16), nullable=False, server_default='active'))
    op.add_column('users', sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=defaults(now)))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))
    create_foundation_tables()
    # Membership has no inbound references, so its composite tenant FK is safe to rebuild.
    with op.batch_alter_table('company_members') as batch:
        batch.add_column(sa.Column('role_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('status', sa.String(16), nullable=False, server_default='active'))
        batch.add_column(sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=defaults(now)))
        batch.add_column(sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key('fk_membership_company_role', 'company_roles', ['role_id', 'company_id'], ['id', 'company_id'])
        batch.create_index('ix_company_members_role_id', ['role_id'])
        batch.create_index('ix_company_members_status', ['status'])
    op.add_column('login_sessions', sa.Column('csrf_token_hash', sa.String(64), nullable=False, server_default=''))
    op.execute(sa.text('ALTER TABLE login_sessions ADD COLUMN selected_company_id INTEGER REFERENCES companies(id)'))
    op.add_column('login_sessions', sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=defaults(now)))
    op.add_column('login_sessions', sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True))
    db.execute(sa.text('UPDATE login_sessions SET revoked_at=:now'), {'now': now})
    db.execute(sa.text('INSERT INTO runtime_mutex (id,value) SELECT 1,0 WHERE NOT EXISTS (SELECT 1 FROM runtime_mutex WHERE id=1)'))
    convert_legacy(db, now)
    for key in PERMISSIONS:
        db.execute(sa.text('INSERT INTO permissions (key, description) VALUES (:key,:description)'), {'key': key, 'description': key.replace('.', ' ').capitalize()})
    for company in db.execute(sa.text('SELECT id, created_at FROM companies')).mappings().all():
        company_id = company['id']
        db.execute(sa.text("INSERT INTO company_settings VALUES (:id,'','','',0,:now)"), {'id': company_id, 'now': now})
        for slug, permissions in ROLES.items():
            role_id = db.execute(sa.text('INSERT INTO company_roles (company_id,name,slug,is_builtin,created_at) VALUES (:company,:name,:slug,1,:now) RETURNING id'), {'company': company_id, 'name': slug.title(), 'slug': slug, 'now': now}).scalar_one()
            for permission in permissions:
                db.execute(sa.text('INSERT INTO role_permission_grants VALUES (:role,:permission)'), {'role': role_id, 'permission': permission})
            db.execute(sa.text('UPDATE company_members SET role_id=:role WHERE company_id=:company AND role=:slug'), {'role': role_id, 'company': company_id, 'slug': slug})
    unknown = db.scalar(sa.text('SELECT COUNT(*) FROM company_members WHERE role_id IS NULL'))
    if unknown:
        raise RuntimeError('Unknown legacy membership role; supply an explicit reviewed role conversion before upgrading.')


def convert_legacy(db, now):
    from app.db.migrations import MigrationError
    raw = context.config.attributes.get('legacy_mapping') or {}
    mapping = {int(key): value for key, value in raw.items()}
    agents = db.execute(sa.text('SELECT a.*, ac.company_id AS managed_company_id FROM agents a LEFT JOIN agent_accounts ac ON ac.id=a.id ORDER BY a.id')).mappings().all()
    known_ids = {agent['id'] for agent in agents}
    if set(mapping) - known_ids:
        raise MigrationError('Legacy mapping contains an unknown agent ID.')
    missing = [agent['id'] for agent in agents if agent['managed_company_id'] is None and agent['id'] not in mapping]
    if missing:
        raise MigrationError(f'Explicit legacy mapping is required for agent IDs: {missing}.')
    companies = dict(db.execute(sa.text('SELECT slug,id FROM companies')).all())
    needs_legacy = 'agentconnect-legacy' in mapping.values()
    if needs_legacy:
        legacy_id = db.execute(sa.text("INSERT INTO companies (name,slug,status,network_opt_in,policy,policy_version,created_at,updated_at) VALUES ('Legacy workspace','agentconnect-legacy','active',0,'{}',1,:now,:now) RETURNING id"), {'now': now}).scalar_one()
        companies['agentconnect-legacy'] = legacy_id
    system_id = None
    for agent in agents:
        company_id = agent['managed_company_id']
        if agent['id'] in mapping:
            target = companies.get(mapping[agent['id']])
            if target is None:
                raise MigrationError('Legacy mapping target must be agentconnect-legacy or an existing company slug.')
            if company_id is not None and company_id != target:
                raise MigrationError('Explicit mapping conflicts with existing managed account ownership.')
            company_id = target
        db.execute(sa.text('UPDATE agents SET company_id=:company WHERE id=:id'), {'company': company_id, 'id': agent['id']})
        if agent['managed_company_id'] is not None:
            continue
        if system_id is None:
            email = 'agentconnect-migration@invalid.local'
            if db.scalar(sa.text('SELECT id FROM users WHERE email=:email'), {'email': email}) is not None:
                raise MigrationError('Reserved migration identity already exists; operator review required.')
            system_id = db.execute(sa.text("INSERT INTO users (email,name,password_hash,status,created_at) VALUES (:email,'Migration system','!disabled-migration-account','disabled',:now) RETURNING id"), {'email': email, 'now': now}).scalar_one()
        interests = db.execute(sa.text('SELECT interest_type,value,weight FROM agent_interests WHERE agent_id=:id ORDER BY id'), {'id': agent['id']}).mappings().all()
        config = {**LEGACY_CONFIG_DEFAULTS, 'name': agent['company_name'], 'description': agent['description'], 'role': agent['role'], 'domain': agent['industry'], 'purpose': agent['description'], 'provider': 'fake', 'model': 'legacy-preserved', 'discoverable': False, 'allow_public': False, 'allow_direct': False, 'allow_group': False, 'categories': [item['value'] for item in interests if item['interest_type'] == 'category'], 'keywords': [item['value'] for item in interests if item['interest_type'] == 'keyword'], 'excluded_topics': [item['value'] for item in interests if item['interest_type'] == 'exclude']}
        version_id = db.execute(sa.text('INSERT INTO agent_versions (agent_id,version,config,created_by,created_at) VALUES (:id,1,:config,:user,:created) RETURNING id'), {'id': agent['id'], 'config': json.dumps(config), 'user': system_id, 'created': agent['created_at']}).scalar_one()
        db.execute(sa.text("INSERT INTO agent_accounts (id,company_id,slug,state,active_version_id,config_version_id,created_at) VALUES (:id,:company,:slug,'draft',NULL,:version,:created)"), {'id': agent['id'], 'company': company_id, 'slug': agent['slug'], 'version': version_id, 'created': agent['created_at']})
    for table, agent_column in (('posts','author_agent_id'), ('notifications','recipient_agent_id'), ('routing_decisions','agent_id'), ('agent_interactions','agent_id'), ('comments','agent_id')):
        db.execute(sa.text(f'UPDATE {table} SET company_id=(SELECT company_id FROM agents WHERE agents.id={table}.{agent_column})'))
        if db.scalar(sa.text(f'SELECT COUNT(*) FROM {table} WHERE company_id IS NULL')):
            raise MigrationError(f'Unresolved historical ownership in {table}.')


def downgrade():
    raise RuntimeError('Downgrade can destroy historical data; restore a verified backup instead.')
