-- ===========================================================================
-- EngHub schema baseline —— 生成于 20261011
--
-- 这是什么：生产库（docker-postgres-1/enghub）当前形态的一次 schema 快照，
--   用 pg_dump --schema-only --no-owner --no-privileges 导出，外加 87 行迁移台账。
--
-- 为什么要它：database/migrations/ 里 25 条已应用迁移的源文件不在仓库
--   （16 条从未进 git，见 ../ledger_gaps.json），所以逐个跑 .sql **重建不出**生产库。
--   新环境建库请直接用这个文件。
--
-- 怎么用：
--   createdb enghub && psql -U enghub -d enghub -f schema_baseline_20261011.sql
--   然后 python scripts/schema_migrate.py   # 只会补台账之后新增的迁移
--
-- 注意：这是 schema-only，**不含业务数据**。
-- ===========================================================================

--
-- PostgreSQL database dump
--

\restrict wMTZ2rr9CKGKb9LClP0mhmgMF7vjctVrTyseYtuKu8SFfI1J2fSkZVVoWt7UNY9

-- Dumped from database version 15.17
-- Dumped by pg_dump version 15.17

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


--
-- Name: amcheck; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS amcheck WITH SCHEMA public;


--
-- Name: EXTENSION amcheck; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION amcheck IS 'functions for verifying relation integrity';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: action_studies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.action_studies (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_id character varying(50) NOT NULL,
    operation_name character varying(100),
    station_id character varying(50),
    operator_id character varying(50),
    study_date timestamp without time zone NOT NULL,
    method_type character varying(50),
    recorded_by character varying(50),
    motions jsonb,
    total_time_cycles double precision,
    analysis_result jsonb,
    duration_min double precision,
    energy_consumption double precision,
    fatigue_level integer,
    improvement_suggestion text,
    motion_analysis_result jsonb,
    ergonomic_score double precision,
    recommended_improvement_suggestion text,
    is_optimized boolean,
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: agent_checkpoints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_checkpoints (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    checkpoint_key character varying(64) NOT NULL,
    request_id character varying(64) NOT NULL,
    messages jsonb DEFAULT '[]'::jsonb NOT NULL,
    messages_fp character varying(64) NOT NULL,
    message_count integer DEFAULT 0 NOT NULL,
    actions_count integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_id character varying(36) NOT NULL,
    event_type character varying(30) NOT NULL,
    agent_key character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    task_id uuid,
    data jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: agent_heartbeats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_heartbeats (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    factory_id character varying(50) NOT NULL,
    agent_key character varying(50) NOT NULL,
    action_taken text,
    trigger_type character varying(50),
    result_summary text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: agent_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    factory_id character varying(50) NOT NULL,
    agent_key character varying(50) NOT NULL,
    agent_name character varying(100) NOT NULL,
    task_type character varying(100) NOT NULL,
    task_desc text,
    status character varying(20) DEFAULT 'running'::character varying NOT NULL,
    progress_pct real DEFAULT 0,
    total_steps integer DEFAULT 1,
    completed_steps integer DEFAULT 0,
    started_at timestamp without time zone DEFAULT now() NOT NULL,
    last_progress_at timestamp without time zone DEFAULT now(),
    completed_at timestamp without time zone,
    timeout_minutes integer DEFAULT 30,
    result jsonb DEFAULT '{}'::jsonb,
    error text,
    retry_count integer DEFAULT 0,
    max_retries integer DEFAULT 3,
    verified boolean DEFAULT false,
    verified_at timestamp without time zone,
    verify_result text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: agent_work_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_work_log (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    agent_key character varying(50) NOT NULL,
    action character varying(50) NOT NULL,
    target character varying(100),
    detail text,
    evidence jsonb DEFAULT '{}'::jsonb,
    result character varying(500),
    related_ref character varying(100),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: ai_action_approvals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_action_approvals (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    session_key character varying(100),
    tool_name character varying(60) NOT NULL,
    tool_label character varying(100),
    arguments jsonb DEFAULT '{}'::jsonb NOT NULL,
    simulated_result jsonb,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    reviewed_at timestamp without time zone,
    reviewed_by character varying(50),
    executed_at timestamp without time zone,
    execution_result jsonb
);


--
-- Name: ai_memories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_memories (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    user_id character varying(50),
    memory_type character varying(30) DEFAULT 'preference'::character varying,
    content text NOT NULL,
    source character varying(100) DEFAULT 'chatbot'::character varying,
    created_at timestamp without time zone DEFAULT now(),
    created_by character varying(50),
    trigger_keywords text,
    action text,
    hit_count integer DEFAULT 0
);


--
-- Name: ai_memory_candidates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_memory_candidates (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    user_id character varying(50),
    memory_type character varying(30) DEFAULT 'preference'::character varying NOT NULL,
    content text NOT NULL,
    source character varying(100) DEFAULT 'chatbot'::character varying,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    reviewed_at timestamp without time zone,
    reviewed_by character varying(50),
    trigger_keywords text,
    action text
);


--
-- Name: alert_intelligence_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alert_intelligence_reviews (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    alert_source character varying(30) NOT NULL,
    alert_ref_id character varying(36) NOT NULL,
    alert_ref_code character varying(100),
    alert_summary text NOT NULL,
    severity_assessment character varying(20),
    root_cause_hypothesis text,
    recommended_actions text,
    dispatch_recommendation character varying(100),
    raw_ai_response text,
    status character varying(20) DEFAULT 'pending'::character varying,
    acknowledged_by character varying(50),
    acknowledged_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: andon_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.andon_categories (
    id character varying(36) DEFAULT gen_random_uuid() NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    is_active boolean DEFAULT true,
    priority_hint character varying(20) DEFAULT 'medium'::character varying,
    requires_leader_approval boolean DEFAULT false,
    auto_route_to_tms boolean DEFAULT false,
    tms_task_type character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: andon_escalation_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.andon_escalation_logs (
    id character varying(36) DEFAULT gen_random_uuid() NOT NULL,
    ticket_id character varying(36) NOT NULL,
    event_type character varying(30) NOT NULL,
    from_role character varying(50),
    to_role character varying(50),
    message text,
    triggered_by character varying(50) DEFAULT 'system'::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: andon_tickets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.andon_tickets (
    id character varying(36) DEFAULT gen_random_uuid() NOT NULL,
    ticket_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    category_id character varying(36),
    category_code character varying(50) NOT NULL,
    title character varying(200) NOT NULL,
    description text,
    location_id character varying(50),
    location_name character varying(100),
    equipment_id character varying(36),
    work_order_id character varying(36),
    status character varying(30) DEFAULT 'open'::character varying NOT NULL,
    priority character varying(20) DEFAULT 'medium'::character varying,
    assigned_to character varying(50),
    assigned_by character varying(50),
    claimed_at timestamp without time zone,
    escalation_level integer DEFAULT 0,
    escalator_note text,
    escalated_to character varying(50),
    escalated_at timestamp without time zone,
    reminder_interval_minutes integer DEFAULT 5,
    last_reminder_at timestamp without time zone,
    timeout_minutes_no_response integer DEFAULT 15,
    timeout_minutes_resolve integer DEFAULT 30,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    resolved_at timestamp without time zone,
    metadata_ jsonb DEFAULT '{}'::jsonb
);


--
-- Name: aps_coordination_meetings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aps_coordination_meetings (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    meeting_date date NOT NULL,
    meeting_type character varying(40) DEFAULT 'production_coordination'::character varying NOT NULL,
    plan_version character varying(80),
    attendees jsonb DEFAULT '[]'::jsonb NOT NULL,
    decisions jsonb DEFAULT '[]'::jsonb NOT NULL,
    action_items jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_by character varying(50) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: aps_dlq_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aps_dlq_requests (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    mode character varying(20),
    horizon_days integer,
    optimize_for character varying(20),
    source_type character varying(30) NOT NULL,
    source_id character varying(50),
    retry_count integer,
    last_error_message text,
    failed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: aps_holidays; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aps_holidays (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    calendar_code character varying(80) NOT NULL,
    year integer NOT NULL,
    holiday_date date NOT NULL,
    holiday_name character varying(150) NOT NULL,
    holiday_type character varying(30) DEFAULT 'legal'::character varying NOT NULL,
    is_working_day boolean DEFAULT false NOT NULL,
    source_name character varying(200),
    source_url character varying(500),
    is_active boolean DEFAULT true NOT NULL,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: aps_plan_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aps_plan_events (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    plan_id character varying(36),
    schedule_id character varying(36),
    work_order_id character varying(36),
    event_type character varying(40) NOT NULL,
    actor character varying(50) NOT NULL,
    reason text,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: aps_planner_activities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aps_planner_activities (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    user_id character varying(50) NOT NULL,
    activity_type character varying(40) NOT NULL,
    source character varying(20) DEFAULT 'aps_ui'::character varying NOT NULL,
    plan_version character varying(80),
    started_at timestamp without time zone NOT NULL,
    ended_at timestamp without time zone,
    duration_minutes numeric(10,2),
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: aps_schedule_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aps_schedule_requests (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    mode character varying(20),
    horizon_days integer,
    optimize_for character varying(20),
    source_type character varying(30),
    source_id character varying(36),
    status character varying(20),
    retry_count integer,
    max_retries integer,
    error_message text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    completed_at timestamp without time zone
);


--
-- Name: aps_schedule_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aps_schedule_tasks (
    id character varying(36) NOT NULL,
    schedule_id character varying(36) NOT NULL,
    work_order_id character varying(36),
    order_code character varying(50),
    product_code character varying(50),
    operation_seq integer NOT NULL,
    operation_name character varying(100),
    station_id character varying(50) NOT NULL,
    planned_start timestamp without time zone NOT NULL,
    planned_end timestamp without time zone NOT NULL,
    setup_seconds double precision DEFAULT 0,
    run_seconds double precision DEFAULT 0,
    quantity integer DEFAULT 0,
    status character varying(20) DEFAULT 'planned'::character varying,
    is_locked boolean DEFAULT false,
    priority integer DEFAULT 5,
    created_at timestamp without time zone DEFAULT now(),
    setup_minutes double precision DEFAULT 0,
    material_ready boolean DEFAULT true,
    sequence_in_station integer,
    actual_start timestamp without time zone,
    actual_end timestamp without time zone,
    deviation_reason text,
    duration_basis character varying(40)
);


--
-- Name: COLUMN aps_schedule_tasks.duration_basis; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.aps_schedule_tasks.duration_basis IS '单件时长的出处：route_declared_hours / declared_line_capacity / station_declared_rate / no_time_basis';


--
-- Name: aps_schedules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aps_schedules (
    id character varying(36) NOT NULL,
    schedule_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    mode character varying(20) DEFAULT 'hybrid'::character varying NOT NULL,
    optimize_for character varying(20) DEFAULT 'delivery'::character varying,
    status character varying(20) DEFAULT 'draft'::character varying,
    horizon_start timestamp without time zone NOT NULL,
    horizon_end timestamp without time zone NOT NULL,
    on_time_rate double precision,
    avg_utilization double precision,
    total_setup_minutes double precision,
    avg_cycle_hours double precision,
    total_tasks integer DEFAULT 0,
    unscheduled_count integer DEFAULT 0,
    created_by character varying(50),
    confirmed_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    algorithm character varying(30) DEFAULT 'EDD'::character varying,
    constraint_summary text,
    conflict_count integer DEFAULT 0,
    priority_level character varying(20),
    constraint_type character varying(50),
    feasibility_status character varying(20),
    approved_by character varying(50),
    released_by character varying(50),
    released_at timestamp without time zone,
    version_number integer DEFAULT 1 NOT NULL,
    is_current boolean DEFAULT false NOT NULL,
    supersedes_schedule_id character varying(36),
    change_reason text,
    input_fingerprint character varying(64)
);


--
-- Name: aps_work_calendars; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aps_work_calendars (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    resource_id character varying(50) NOT NULL,
    resource_type character varying(20) DEFAULT 'station'::character varying,
    shift_name character varying(50) DEFAULT '标准班'::character varying,
    day_of_week integer NOT NULL,
    start_time time without time zone NOT NULL,
    end_time time without time zone NOT NULL,
    is_active boolean DEFAULT true,
    effective_from date,
    effective_to date
);


--
-- Name: archive_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.archive_records (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    record_type character varying(20) NOT NULL,
    source_id character varying(36),
    title character varying(300),
    summary text,
    status character varying(20),
    owner character varying(100),
    meta jsonb DEFAULT '{}'::jsonb,
    archived_at timestamp without time zone DEFAULT now() NOT NULL,
    expires_at timestamp without time zone
);


--
-- Name: arrival_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.arrival_plans (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    po_code character varying(50) NOT NULL,
    material_code character varying(100) NOT NULL,
    supplier_id character varying(50),
    quantity numeric(14,2) NOT NULL,
    eta_date date NOT NULL,
    transport character varying(50) DEFAULT '陆运'::character varying,
    status character varying(20) DEFAULT 'scheduled'::character varying,
    updated_by character varying(50),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: attendance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attendance (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    operator_id character varying(36) NOT NULL,
    date character varying(10) NOT NULL,
    check_in timestamp without time zone,
    check_out timestamp without time zone,
    shift character varying(20) NOT NULL,
    status character varying(20) NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: automation_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_config (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    factory_id character varying(50) NOT NULL,
    workflow_key character varying(50) NOT NULL,
    workflow_name character varying(100) NOT NULL,
    automation_level integer DEFAULT 1 NOT NULL,
    description text,
    auto_rules jsonb DEFAULT '{}'::jsonb,
    updated_by character varying(100),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: bom_items_row_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bom_items_row_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bom_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bom_items (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_id character varying(50) NOT NULL,
    bom_version character varying(50) NOT NULL,
    material_code character varying(50) NOT NULL,
    material_name character varying(100),
    qty_per_unit numeric(12,4) DEFAULT 1 NOT NULL,
    unit character varying(20) DEFAULT 'pcs'::character varying,
    level integer DEFAULT 1 NOT NULL,
    remark character varying(255),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    row_id bigint DEFAULT nextval('public.bom_items_row_id_seq'::regclass),
    company_id character varying(50),
    product_sap_code character varying(100),
    part_number character varying(100),
    description text,
    quantity double precision,
    unit_price double precision,
    total_cost double precision,
    vendor_code character varying(50),
    vendor_name character varying(255),
    parent_sap character varying(100),
    model_name character varying(100)
);


--
-- Name: bom_items_backup_20260807; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bom_items_backup_20260807 (
    id character varying(36),
    factory_id character varying(50),
    product_id character varying(50),
    bom_version character varying(50),
    material_code character varying(50),
    material_name character varying(100),
    qty_per_unit numeric(12,4),
    unit character varying(20),
    level integer,
    remark character varying(255),
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    row_id bigint,
    company_id character varying(50),
    product_sap_code character varying(100),
    part_number character varying(100),
    description text,
    quantity double precision,
    unit_price double precision,
    total_cost double precision,
    vendor_code character varying(50),
    vendor_name character varying(255),
    parent_sap character varying(100),
    model_name character varying(100)
);


--
-- Name: capa_cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.capa_cases (
    id character varying(36) NOT NULL,
    case_number character varying(50) NOT NULL,
    problem_description text,
    discovery_date timestamp without time zone,
    defect_severity character varying(20),
    root_cause text,
    corrective_action text,
    preventive_action text,
    assigned_to character varying(50),
    deadline timestamp without time zone,
    status character varying(20),
    effectiveness_check_date timestamp without time zone,
    verification_result text,
    preventive_scope text,
    action_logs jsonb,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    why_analysis jsonb,
    fishbone_dimensions jsonb,
    interim_actions_detailed jsonb,
    corrective_action_plans jsonb,
    verification_results jsonb,
    preventive_updates jsonb,
    lessons_learned_doc text,
    verification_before jsonb,
    verification_after jsonb,
    verification_improved boolean,
    verification_by character varying(50)
);


--
-- Name: capa_fishbone_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.capa_fishbone_items (
    id character varying(36) NOT NULL,
    case_id character varying(50) NOT NULL,
    dimension character varying(50) NOT NULL,
    item text NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: capa_why_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.capa_why_steps (
    id character varying(36) NOT NULL,
    case_id character varying(50) NOT NULL,
    step_num integer NOT NULL,
    question text,
    answer text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: chat_eval_cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_eval_cases (
    id character varying(36) NOT NULL,
    name character varying(120) NOT NULL,
    prompt text NOT NULL,
    expected_tool character varying(64),
    expected_reply_keyword character varying(120),
    model character varying(64),
    factory_id character varying(32) DEFAULT 'F01'::character varying NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: chat_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_events (
    id character varying(36) NOT NULL,
    event_id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    request_id character varying(64) NOT NULL,
    sequence bigint NOT NULL,
    event_type character varying(64) NOT NULL,
    item_id character varying(64),
    data jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: chat_goal_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_goal_metrics (
    id character varying(36) NOT NULL,
    goal_id character varying(36) NOT NULL,
    metric_code character varying(40) NOT NULL,
    label character varying(120) NOT NULL,
    comparator character varying(8) DEFAULT 'gte'::character varying NOT NULL,
    target_value numeric(18,4),
    unit character varying(32),
    current_value numeric(18,4),
    status character varying(20) DEFAULT 'observed'::character varying NOT NULL,
    source_tool character varying(80),
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_checked_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: chat_goals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_goals (
    id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    factory_id character varying(32) NOT NULL,
    user_id character varying(36) NOT NULL,
    objective text NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    token_budget integer,
    tokens_used integer DEFAULT 0 NOT NULL,
    time_used_seconds integer DEFAULT 0 NOT NULL,
    progress_pct integer DEFAULT 0 NOT NULL,
    summary text,
    blocked_reason text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    cleared_at timestamp without time zone
);


--
-- Name: chat_memories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_memories (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    factory_id character varying(32),
    key character varying(64) NOT NULL,
    value text NOT NULL,
    confidence smallint DEFAULT 2 NOT NULL,
    source character varying(32) DEFAULT 'chat'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: chat_message_attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_message_attachments (
    id character varying(36) NOT NULL,
    message_id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    file_id character varying(36) NOT NULL,
    kind character varying(16),
    ordinal integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: chat_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_messages (
    id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    role character varying(16) NOT NULL,
    content text,
    tool_calls jsonb,
    tool_results jsonb,
    model character varying(64),
    tokens_used integer DEFAULT 0 NOT NULL,
    duration_ms integer DEFAULT 0 NOT NULL,
    request_id character varying(64),
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: chat_quick_commands; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_quick_commands (
    id character varying(36) NOT NULL,
    factory_id character varying(64),
    created_by character varying(64),
    command_text character varying(500) NOT NULL,
    agent_key character varying(64),
    agent_name character varying(64),
    classify_source character varying(16) DEFAULT 'auto'::character varying,
    is_preset boolean DEFAULT false,
    sort_order integer DEFAULT 100,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    scope character varying(16) DEFAULT 'all'::character varying
);


--
-- Name: TABLE chat_quick_commands; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.chat_quick_commands IS 'Chatbot 快速命令（预设语句 + 用户自定义，自动归类智能体）';


--
-- Name: chat_session_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_session_events (
    id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    request_id character varying(64),
    seq integer NOT NULL,
    event_type character varying(32) NOT NULL,
    data jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: chat_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_sessions (
    id character varying(36) NOT NULL,
    factory_id character varying(32) NOT NULL,
    user_id character varying(36),
    title character varying(255),
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: chat_telemetry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_telemetry (
    id character varying(36) NOT NULL,
    request_id character varying(64) NOT NULL,
    session_id character varying(36),
    phase character varying(32) DEFAULT 'total'::character varying NOT NULL,
    duration_ms numeric(10,2) DEFAULT 0 NOT NULL,
    model character varying(64),
    provider character varying(32),
    tools_called jsonb DEFAULT '[]'::jsonb NOT NULL,
    rounds integer DEFAULT 0 NOT NULL,
    success boolean DEFAULT true NOT NULL,
    error text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: chatbot_ticket_approval_flow; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chatbot_ticket_approval_flow (
    id character varying(36) NOT NULL,
    ticket_id character varying(36),
    step integer NOT NULL,
    role_required character varying(50),
    approver_id character varying(50),
    decision character varying(20),
    decision_at timestamp without time zone,
    comment text
);


--
-- Name: chatbot_tickets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chatbot_tickets (
    id character varying(36) NOT NULL,
    ticket_code character varying(50) NOT NULL,
    requester_id character varying(50) NOT NULL,
    requester_org_unit character varying(36),
    ticket_type character varying(30) NOT NULL,
    raw_message text NOT NULL,
    parsed_intents jsonb DEFAULT '{}'::jsonb,
    parsed_slots jsonb DEFAULT '{}'::jsonb,
    requested_resource jsonb DEFAULT '{}'::jsonb,
    requested_time_window jsonb DEFAULT '{}'::jsonb,
    related_param_id character varying(36),
    related_rcc_task_id character varying(36),
    related_andon_id character varying(36),
    related_work_order_id character varying(36),
    status character varying(20) DEFAULT 'open'::character varying,
    priority character varying(20) DEFAULT 'medium'::character varying,
    routed_to_org_unit character varying(36),
    routed_to_position character varying(50),
    resolved_by character varying(50),
    resolution text,
    resolved_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: code_tables; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.code_tables (
    id character varying(36) NOT NULL,
    category character varying(50) NOT NULL,
    code character varying(30) NOT NULL,
    name character varying(100) NOT NULL,
    name_en character varying(100),
    description character varying(255),
    keywords jsonb,
    extra jsonb,
    sort_order integer DEFAULT 0,
    is_active boolean DEFAULT true,
    is_system boolean DEFAULT false,
    factory_id character varying(50),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    created_by character varying(50),
    updated_by character varying(50)
);


--
-- Name: commander_cycles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.commander_cycles (
    id bigint NOT NULL,
    factory_id character varying(64) DEFAULT 'FAC_MECH_001'::character varying NOT NULL,
    mode character varying(20) DEFAULT 'healthy'::character varying NOT NULL,
    cycle jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by character varying(64) DEFAULT ''::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: commander_cycles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.commander_cycles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: commander_cycles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.commander_cycles_id_seq OWNED BY public.commander_cycles.id;


--
-- Name: commander_decision_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.commander_decision_log (
    id character varying(36) NOT NULL,
    factory_id character varying(64) NOT NULL,
    cycle_id character varying(36) NOT NULL,
    mode character varying(20) NOT NULL,
    mode_source character varying(16) DEFAULT 'policy'::character varying NOT NULL,
    mode_reason character varying(500),
    state_snapshot jsonb NOT NULL,
    decisions jsonb DEFAULT '[]'::jsonb NOT NULL,
    policy_version character varying(64) NOT NULL,
    duration_ms integer,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: commander_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.commander_plans (
    id character varying(36) NOT NULL,
    factory_id character varying(64) NOT NULL,
    created_by character varying(64) NOT NULL,
    cycle_id character varying(36),
    objective character varying(500) NOT NULL,
    mode character varying(20),
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    progress_pct integer DEFAULT 0 NOT NULL,
    item_count integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    closed_at timestamp with time zone
);


--
-- Name: TABLE commander_plans; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.commander_plans IS '工厂指挥官行动计划：决策聚合为目标导向计划，子任务挂 followup_tasks 持续盯办';


--
-- Name: commander_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.commander_sessions (
    user_id character varying(64) NOT NULL,
    factory_id character varying(64) NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    scope jsonb DEFAULT '{}'::jsonb NOT NULL,
    username character varying(64),
    enabled_at timestamp without time zone
);


--
-- Name: cost_parameters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cost_parameters (
    id character varying(64) NOT NULL,
    factory_id character varying(64),
    item_code character varying(64) NOT NULL,
    amount numeric(18,4) NOT NULL,
    is_hard boolean,
    currency character varying(8) DEFAULT 'USD'::character varying,
    source character varying(256),
    note text,
    valid_from date,
    valid_to date,
    created_by character varying(64) DEFAULT 'system'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE cost_parameters; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.cost_parameters IS '成本模型的可覆盖参数：没填就用内置标定并在结果里标 basis=default_calibration，填了必须带 source';


--
-- Name: crew_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.crew_decisions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    factory_id character varying(50) NOT NULL,
    crew_key character varying(50),
    crew_name character varying(100),
    context jsonb,
    decision jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: cycle_count_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cycle_count_items (
    id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    material_id character varying(50) NOT NULL,
    material_code character varying(50),
    location_id character varying(36),
    system_qty integer DEFAULT 0,
    counted_qty integer,
    diff_qty integer,
    status character varying(20) DEFAULT 'pending'::character varying,
    counted_by character varying(50),
    counted_at timestamp without time zone,
    remark character varying(200),
    created_at timestamp without time zone DEFAULT now(),
    variance_reason character varying(500),
    adjusted boolean DEFAULT false
);


--
-- Name: cycle_count_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cycle_count_tasks (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    task_code character varying(50) NOT NULL,
    warehouse_id character varying(36),
    zone character varying(50),
    count_type character varying(20) DEFAULT 'cycle'::character varying,
    status character varying(20) DEFAULT 'pending'::character varying,
    total_items integer DEFAULT 0,
    counted_items integer DEFAULT 0,
    diff_items integer DEFAULT 0,
    assigned_to character varying(50),
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    accuracy_rate double precision,
    total_diff_qty integer DEFAULT 0,
    remark text,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    approval_status character varying(20) DEFAULT 'none'::character varying,
    approved_by character varying(50),
    approved_at timestamp without time zone,
    variance_adjusted boolean DEFAULT false
);


--
-- Name: decision_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.decision_records (
    id text NOT NULL,
    factory_id text NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    state jsonb DEFAULT '{}'::jsonb NOT NULL,
    candidates jsonb DEFAULT '[]'::jsonb NOT NULL,
    action jsonb DEFAULT '{}'::jsonb NOT NULL,
    outcome jsonb DEFAULT '{}'::jsonb NOT NULL,
    outcome_source text DEFAULT 'unknown'::text NOT NULL,
    linked_task_id text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: defect_daily_summary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.defect_daily_summary (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    summary_date date NOT NULL,
    defect_type character varying(50) NOT NULL,
    defect_name character varying(100),
    station_id character varying(50),
    product_id character varying(50),
    defect_count integer DEFAULT 0,
    inspected_qty integer DEFAULT 0,
    critical_count integer DEFAULT 0,
    major_count integer DEFAULT 0,
    minor_count integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: defect_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.defect_records (
    id character varying(36) NOT NULL,
    record_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    work_order_id character varying(36),
    production_report_id character varying(36),
    product_id character varying(36),
    material_id character varying(50),
    batch_code character varying(50),
    station_id character varying(50),
    equipment_id character varying(36),
    defect_type character varying(50) NOT NULL,
    severity character varying(20) DEFAULT 'minor'::character varying NOT NULL,
    quantity integer DEFAULT 0 NOT NULL,
    disposition character varying(20),
    disposition_by character varying(50),
    disposition_at timestamp without time zone,
    disposition_remark text,
    ocap_status character varying(20) DEFAULT 'pending'::character varying,
    description text,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    is_finalized boolean DEFAULT false,
    defect_source character varying(30),
    root_cause_category character varying(30),
    root_cause text,
    responsible_dept character varying(30),
    discovery_stage character varying(20),
    discovery_time timestamp without time zone,
    defect_location character varying(200),
    inspection_id character varying(36),
    corrective_action text,
    preventive_action text,
    process_step character varying(50),
    review_status character varying(20) DEFAULT 'pending'::character varying,
    reviewed_by character varying(50),
    reviewed_at timestamp without time zone,
    defect_classification character varying(50),
    failure_mode character varying(100),
    rpn_value integer,
    corrective_action_link character varying(500),
    ocap_trigger_reason character varying(200)
);


--
-- Name: defects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.defects (
    id character varying(36) NOT NULL,
    defect_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    defect_type character varying(50) NOT NULL,
    quantity integer NOT NULL,
    severity character varying(20) NOT NULL,
    inspection_id character varying(36),
    work_order_id character varying(36),
    material_id character varying(50),
    batch_id character varying(50),
    station_id character varying(50),
    description text,
    status character varying(20) NOT NULL,
    disposition character varying(20),
    disposition_by character varying(50),
    disposition_at timestamp without time zone,
    disposition_qty integer,
    disposition_remark text,
    ocap_status character varying(20),
    ocap_triggered_at timestamp without time zone,
    ocap_trigger_reason text,
    created_by character varying(50),
    updated_by character varying(50),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: departments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.departments (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    dept_code character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    manager_id character varying(50),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: deterministic_logic_chains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deterministic_logic_chains (
    id character varying(36) NOT NULL,
    chain_code character varying(50) NOT NULL,
    chain_name character varying(100) NOT NULL,
    org_unit_id character varying(36),
    position_cap_id character varying(36),
    trigger_event character varying(100) NOT NULL,
    conditions jsonb DEFAULT '[]'::jsonb NOT NULL,
    action_sequence jsonb DEFAULT '[]'::jsonb NOT NULL,
    enabled boolean DEFAULT true,
    execution_order integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: employee_skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.employee_skills (
    id integer NOT NULL,
    user_id character varying(36) NOT NULL,
    skill_id integer NOT NULL,
    level character varying(10) NOT NULL,
    certified_date timestamp without time zone,
    expiry_date timestamp without time zone,
    score numeric(5,2),
    remarks text,
    evaluated_by character varying(36),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone,
    training_record_link character varying(500),
    competency_assessment_score numeric(5,2),
    skill_level_date date
);


--
-- Name: employee_skills_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.employee_skills_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: employee_skills_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.employee_skills_id_seq OWNED BY public.employee_skills.id;


--
-- Name: enghub_bom_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enghub_bom_items (
    id integer NOT NULL,
    source_row_id bigint,
    product_model character varying(100),
    part_number character varying(100),
    description text,
    level integer,
    quantity double precision,
    unit character varying(20),
    unit_price double precision,
    total_cost double precision,
    vendor_code character varying(50),
    vendor_name character varying(255),
    parent_part character varying(100),
    category_l1 character varying(100),
    category_l2 character varying(100),
    material_family character varying(100),
    component_type character varying(100),
    synced_at timestamp without time zone,
    source_updated_at timestamp without time zone,
    factory_id character varying(50),
    is_production boolean DEFAULT false,
    source_file character varying(500),
    original_row_number bigint,
    l2_parent_group character varying(200),
    l3_context character varying(200)
);


--
-- Name: COLUMN enghub_bom_items.factory_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.enghub_bom_items.factory_id IS 'EngHub 工厂 ID，EngFlow BOM 仅同步至 FAC_MECH_001';


--
-- Name: enghub_bom_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.enghub_bom_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: enghub_bom_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.enghub_bom_items_id_seq OWNED BY public.enghub_bom_items.id;


--
-- Name: enghub_bom_sync_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enghub_bom_sync_log (
    id integer NOT NULL,
    sync_type character varying(20),
    status character varying(20),
    records_synced integer,
    watermark timestamp without time zone,
    started_at timestamp without time zone,
    finished_at timestamp without time zone,
    error_message text,
    factory_id character varying(50),
    source_company_id character varying(50)
);


--
-- Name: enghub_bom_sync_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.enghub_bom_sync_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: enghub_bom_sync_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.enghub_bom_sync_log_id_seq OWNED BY public.enghub_bom_sync_log.id;


--
-- Name: enghub_schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enghub_schema_migrations (
    migration_name character varying(255) NOT NULL,
    checksum character varying(64) NOT NULL,
    applied_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: engine_loop_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.engine_loop_state (
    loop_name character varying(64) NOT NULL,
    host character varying(120),
    pid integer,
    interval_seconds integer DEFAULT 300 NOT NULL,
    started_at timestamp without time zone,
    last_tick_at timestamp without time zone,
    ticks bigint DEFAULT 0 NOT NULL,
    failures bigint DEFAULT 0 NOT NULL,
    last_status character varying(16),
    last_error text,
    last_detail jsonb,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    recent_errors jsonb DEFAULT '[]'::jsonb NOT NULL,
    window_started_at timestamp without time zone,
    window_ticks bigint DEFAULT 0 NOT NULL,
    window_failures bigint DEFAULT 0 NOT NULL
);


--
-- Name: engine_order_predictions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.engine_order_predictions (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    work_order_id text NOT NULL,
    work_order_code character varying(50),
    model_code character varying(50),
    units numeric,
    made_on date NOT NULL,
    planned_due date,
    predicted_finish date,
    estimated_days numeric,
    line_code character varying(50),
    basis character varying(40) NOT NULL,
    actual_complete date,
    error_days integer,
    paired_on timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: engineering_changes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.engineering_changes (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    ecn_code character varying(50) NOT NULL,
    title character varying(300) NOT NULL,
    change_type character varying(30) DEFAULT 'process'::character varying,
    affected_product character varying(100),
    affected_routing_id character varying(36),
    description text,
    old_value text,
    new_value text,
    status character varying(20) DEFAULT 'draft'::character varying,
    affected_wo_count integer DEFAULT 0,
    propagated_at timestamp without time zone,
    created_by character varying(50),
    approved_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: engineering_forms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.engineering_forms (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    form_type character varying(30) NOT NULL,
    form_code character varying(50),
    title character varying(255) NOT NULL,
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    severity character varying(10) DEFAULT 'major'::character varying,
    status character varying(20) DEFAULT 'draft'::character varying,
    assignee character varying(50),
    assignee_role character varying(50),
    due_date timestamp without time zone,
    reviewer character varying(50),
    review_comment text,
    source character varying(30) DEFAULT 'chatbot'::character varying,
    source_ref character varying(50),
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: enterprise_knowledge_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enterprise_knowledge_documents (
    id bigint NOT NULL,
    document_code character varying(100) NOT NULL,
    role_code character varying(64),
    industry_code character varying(64) DEFAULT 'generic'::character varying NOT NULL,
    category character varying(64) DEFAULT 'general'::character varying NOT NULL,
    title character varying(255) NOT NULL,
    summary text,
    content_md text NOT NULL,
    tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    source_type character varying(64) DEFAULT 'curated'::character varying NOT NULL,
    source_ref character varying(255),
    version character varying(32) DEFAULT '1.0'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: enterprise_knowledge_documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.enterprise_knowledge_documents_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: enterprise_knowledge_documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.enterprise_knowledge_documents_id_seq OWNED BY public.enterprise_knowledge_documents.id;


--
-- Name: equipment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.equipment (
    id character varying(36) NOT NULL,
    equipment_code character varying(50) NOT NULL,
    equipment_name character varying(100) NOT NULL,
    factory_id character varying(50) NOT NULL,
    station_id character varying(50),
    equipment_type character varying(50),
    status character varying(20),
    last_maintenance_date timestamp without time zone,
    next_maintenance_date timestamp without time zone,
    spec jsonb,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    manufacturer_model character varying(100),
    serial_number character varying(100),
    purchase_date date,
    warranty_expiry date,
    maintenance_interval_days integer,
    responsible_engineer_id character varying(36)
);


--
-- Name: equipment_downtime; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.equipment_downtime (
    id character varying(36) NOT NULL,
    equipment_id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    start_time timestamp without time zone NOT NULL,
    end_time timestamp without time zone,
    duration_minutes double precision,
    downtime_category character varying(30),
    reason_code character varying(50),
    description text,
    reported_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    created_by character varying(50),
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: equipment_readings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.equipment_readings (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    equipment_id character varying(50) NOT NULL,
    metric_type character varying(30) NOT NULL,
    metric_value double precision NOT NULL,
    unit character varying(20),
    warning_threshold double precision,
    alarm_threshold double precision,
    is_alarm boolean DEFAULT false,
    recorded_at timestamp without time zone DEFAULT now(),
    recorded_by character varying(50)
);


--
-- Name: erp_inbound; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.erp_inbound (
    id character varying(36) NOT NULL,
    source character varying(20) DEFAULT 'sap'::character varying,
    doc_type character varying(30) DEFAULT 'production_order'::character varying NOT NULL,
    doc_number character varying(50) NOT NULL,
    product_code character varying(50),
    quantity integer DEFAULT 0,
    due_date date,
    order_type character varying(20) DEFAULT 'PP01'::character varying,
    priority character varying(20) DEFAULT 'medium'::character varying,
    status character varying(20) DEFAULT 'pending'::character varying,
    remark text,
    created_at timestamp without time zone DEFAULT now(),
    synced_at timestamp without time zone
);


--
-- Name: erp_outbound; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.erp_outbound (
    id character varying(36) NOT NULL,
    doc_type character varying(30) DEFAULT 'confirmation'::character varying NOT NULL,
    doc_number character varying(50) NOT NULL,
    work_order_code character varying(50),
    report_code character varying(50),
    product_code character varying(50),
    good_qty integer DEFAULT 0,
    defect_qty integer DEFAULT 0,
    confirm_at timestamp without time zone,
    status character varying(20) DEFAULT 'pending'::character varying,
    created_at timestamp without time zone DEFAULT now(),
    sent_at timestamp without time zone
);


--
-- Name: execution_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.execution_events (
    id text NOT NULL,
    factory_id text NOT NULL,
    occurred_at timestamp without time zone DEFAULT now() NOT NULL,
    action text NOT NULL,
    line_code text,
    section text,
    model_code text,
    people integer,
    hours numeric,
    units numeric,
    note text,
    actor text,
    source text DEFAULT 'manual'::text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: factories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.factories (
    id character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    short_name character varying(50),
    factory_type character varying(50),
    address text,
    contact_person character varying(50),
    contact_phone character varying(30),
    status character varying(20) DEFAULT 'active'::character varying,
    config jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: factory_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.factory_rules (
    id text NOT NULL,
    factory_id text NOT NULL,
    kind text DEFAULT 'constraint'::text NOT NULL,
    subject text NOT NULL,
    verdict text NOT NULL,
    statement text,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'candidate'::text NOT NULL,
    source text DEFAULT 'derived'::text NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    asked_by text,
    confirmed_by text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.files (
    id character varying(36) NOT NULL,
    filename character varying(255) NOT NULL,
    content_type character varying(100),
    size bigint DEFAULT 0,
    storage_path character varying(500) NOT NULL,
    uploaded_by character varying(50),
    factory_id character varying(50),
    related_type character varying(50),
    related_id character varying(50),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: five_s_audits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.five_s_audits (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    work_center_id character varying(50) NOT NULL,
    audit_date timestamp without time zone NOT NULL,
    auditor_id character varying(50),
    seiri_score integer,
    seiton_score integer,
    seiso_score integer,
    seiketsu_score integer,
    shitsuke_score integer,
    improvement_items json,
    next_audit_date timestamp without time zone,
    total_score integer,
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: followup_task_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.followup_task_logs (
    id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    factory_id character varying(50),
    trigger_type character varying(30),
    note text,
    status_after character varying(20),
    progress_pct numeric(5,2),
    created_by character varying(50),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE followup_task_logs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.followup_task_logs IS '任务中心跟进历史（定期扫描与手动跟进的时间线留痕）';


--
-- Name: followup_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.followup_tasks (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    created_by character varying(50),
    title character varying(200) NOT NULL,
    description text,
    agent_key character varying(50),
    agent_name character varying(100),
    status character varying(20) DEFAULT 'open'::character varying,
    block_reason text,
    source character varying(50),
    conversation_hint character varying(200),
    follow_interval_minutes integer DEFAULT 30,
    next_follow_at timestamp with time zone,
    last_follow_at timestamp with time zone,
    last_follow_note text,
    follow_count integer DEFAULT 0,
    max_follows integer DEFAULT 10,
    progress_pct numeric(5,2) DEFAULT 0,
    result_summary text,
    item_type character varying(30),
    assigned_to character varying(50),
    ai_summary text,
    ai_suggestion text,
    payload jsonb,
    due_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    closed_at timestamp with time zone,
    plan_id character varying(36),
    plan_seq integer,
    blocked_by character varying(100),
    block_category character varying(30)
);


--
-- Name: TABLE followup_tasks; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.followup_tasks IS '任务中心：暂时无法完成的任务挂账跟进，按 follow_interval_minutes 定期扫描';


--
-- Name: COLUMN followup_tasks.item_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.followup_tasks.item_type IS '条目类型: followup/assigned/meeting/email/note';


--
-- Name: COLUMN followup_tasks.ai_summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.followup_tasks.ai_summary IS 'AI 分诊摘要';


--
-- Name: COLUMN followup_tasks.ai_suggestion; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.followup_tasks.ai_suggestion IS 'AI 建议动作/行动项';


--
-- Name: COLUMN followup_tasks.payload; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.followup_tasks.payload IS '原始内容（会议纪要/邮件正文）';


--
-- Name: COLUMN followup_tasks.plan_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.followup_tasks.plan_id IS '所属指挥官计划（commander_plans.id），NULL=非计划任务';


--
-- Name: COLUMN followup_tasks.plan_seq; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.followup_tasks.plan_seq IS '计划内序号（按优先级排序，1 最优先）';


--
-- Name: global_adjustable_params; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.global_adjustable_params (
    id character varying(36) NOT NULL,
    param_code character varying(100) NOT NULL,
    param_name character varying(100) NOT NULL,
    org_unit_id character varying(36),
    position_cap_id character varying(36),
    category character varying(20) NOT NULL,
    param_type character varying(20) NOT NULL,
    default_value character varying,
    current_value character varying,
    effective_from timestamp with time zone DEFAULT now(),
    target_value character varying,
    min_value double precision,
    max_value double precision,
    step_value double precision,
    unit character varying(50),
    options jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    sensitivity character varying(20) DEFAULT 'normal'::character varying,
    affects_logic_chains jsonb DEFAULT '[]'::jsonb,
    rollback_allowed boolean DEFAULT true,
    rollback_window_minutes integer DEFAULT 60,
    changed_by character varying(50),
    change_reason text,
    previous_value character varying
);


--
-- Name: goods_receipts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.goods_receipts (
    id character varying(36) NOT NULL,
    gr_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    po_id character varying(50) NOT NULL,
    material_code character varying(100) NOT NULL,
    supplier_id character varying(50),
    quantity numeric(14,2) NOT NULL,
    qty_accepted numeric(14,2) NOT NULL,
    qty_rejected numeric(14,2) DEFAULT 0,
    iqc_status character varying(20) DEFAULT 'pending'::character varying,
    warehouse character varying(50) DEFAULT 'MAIN'::character varying,
    received_by character varying(50) DEFAULT 'procurement_agent'::character varying,
    received_at timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now(),
    inspection_task_id character varying(50)
);


--
-- Name: hourly_output_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hourly_output_snapshots (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    snapshot_date date NOT NULL,
    snapshot_hour integer NOT NULL,
    station_id character varying(50),
    output_qty integer DEFAULT 0,
    good_qty integer DEFAULT 0,
    defect_qty integer DEFAULT 0,
    target_qty integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT now(),
    created_by character varying(50),
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: hr_employee_skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hr_employee_skills (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    hr_employee_id character varying(36) NOT NULL,
    skill_id integer NOT NULL,
    level character varying(10) DEFAULT 'L1'::character varying NOT NULL,
    certified_date date,
    expiry_date date,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: hr_employees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hr_employees (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    factory_id character varying(50) NOT NULL,
    employee_code character varying(30) NOT NULL,
    name character varying(50) NOT NULL,
    gender character varying(4) DEFAULT '男'::character varying,
    department character varying(50) NOT NULL,
    station character varying(50) NOT NULL,
    "position" character varying(50) DEFAULT '操作员'::character varying,
    shift character varying(20) DEFAULT '白班'::character varying,
    hire_date date DEFAULT CURRENT_DATE,
    status character varying(20) DEFAULT 'active'::character varying,
    phone character varying(20),
    skill_level character varying(10) DEFAULT 'L1'::character varying,
    certifications text[],
    remarks text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    height_cm numeric(5,1),
    weight_kg numeric(5,1),
    expertise_tags jsonb DEFAULT '[]'::jsonb
);


--
-- Name: im_group_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.im_group_members (
    id character varying(36) NOT NULL,
    group_id character varying(36),
    user_id character varying(36),
    display_name character varying(50),
    role character varying(20) DEFAULT 'member'::character varying,
    joined_at timestamp without time zone DEFAULT now()
);


--
-- Name: im_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.im_groups (
    id character varying(36) NOT NULL,
    factory_id character varying(50),
    name character varying(100) NOT NULL,
    description character varying(500),
    group_type character varying(30) DEFAULT 'org'::character varying,
    org_node_id character varying(50),
    owner_id character varying(36),
    avatar_color character varying(20) DEFAULT '#1890ff'::character varying,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: im_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.im_messages (
    id character varying(36) NOT NULL,
    group_id character varying(36),
    sender_id character varying(36),
    sender_name character varying(50),
    msg_type character varying(20) DEFAULT 'text'::character varying,
    content text,
    command_type character varying(30),
    command_payload jsonb,
    reply_to_id character varying(36),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: inbound_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inbound_orders (
    id character varying(36) NOT NULL,
    inbound_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    warehouse_id character varying(36) NOT NULL,
    material_id character varying(50) NOT NULL,
    material_code character varying(50) NOT NULL,
    quantity integer NOT NULL,
    batch_code character varying(50),
    supplier_id character varying(50),
    purchase_order_id character varying(50),
    unit_cost numeric(10,2),
    location_id character varying(36),
    inbound_type character varying(20),
    status character varying(20),
    created_by character varying(50),
    created_at timestamp without time zone NOT NULL,
    completed_at timestamp without time zone,
    production_order_id character varying(50)
);


--
-- Name: industry_knowledge; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.industry_knowledge (
    id integer NOT NULL,
    industry_code character varying(64) NOT NULL,
    category character varying(64) NOT NULL,
    title character varying(255) NOT NULL,
    content text NOT NULL,
    tags jsonb,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: industry_knowledge_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.industry_knowledge_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: industry_knowledge_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.industry_knowledge_id_seq OWNED BY public.industry_knowledge.id;


--
-- Name: inspection_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inspection_items (
    id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    seq integer DEFAULT 1,
    item_name character varying(200) NOT NULL,
    item_code character varying(50),
    category character varying(30),
    spec_value character varying(100),
    upper_limit double precision,
    lower_limit double precision,
    target_value double precision,
    measured_value double precision,
    is_pass boolean,
    defect_type character varying(50),
    severity character varying(20),
    remark character varying(200),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: inspection_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inspection_records (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    inspection_type character varying(50),
    result character varying(20),
    inspector character varying(50),
    notes text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: inspection_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inspection_tasks (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    task_code character varying(50) NOT NULL,
    inspect_type character varying(10) NOT NULL,
    source_type character varying(30),
    source_id character varying(36),
    source_code character varying(50),
    material_id character varying(50),
    material_code character varying(50),
    material_name character varying(100),
    product_id character varying(50),
    work_order_id character varying(36),
    station_id character varying(50),
    batch_qty integer DEFAULT 0,
    sample_qty integer DEFAULT 0,
    aql_level character varying(20) DEFAULT 'General-II'::character varying,
    status character varying(20) DEFAULT 'pending'::character varying,
    defect_qty integer DEFAULT 0,
    defect_rate double precision DEFAULT 0,
    result character varying(20),
    disposition character varying(30),
    inspector character varying(50),
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    remark text,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: inspections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inspections (
    id character varying(36) NOT NULL,
    inspection_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    inspection_type character varying(20) NOT NULL,
    product_id character varying(50),
    material_id character varying(50),
    batch_id character varying(50),
    batch_size integer,
    work_order_id character varying(36),
    aql_level double precision,
    inspection_level character varying(20),
    sample_size integer,
    status character varying(20) NOT NULL,
    inspected_qty integer,
    defective_qty integer,
    inspector_id character varying(50),
    inspected_at timestamp without time zone,
    aql_result json,
    remarks text,
    created_by character varying(50),
    updated_by character varying(50),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: internal_meeting_attendees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.internal_meeting_attendees (
    id character varying(36) NOT NULL,
    meeting_id character varying(36) NOT NULL,
    attendee character varying(120) NOT NULL,
    response_status character varying(20) DEFAULT 'invited'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: internal_meetings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.internal_meetings (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    title character varying(200) NOT NULL,
    agenda text,
    organizer_id character varying(100) NOT NULL,
    group_id character varying(36) NOT NULL,
    status character varying(30) DEFAULT 'scheduled'::character varying NOT NULL,
    starts_at timestamp without time zone NOT NULL,
    duration_minutes integer DEFAULT 30 NOT NULL,
    created_by character varying(100) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: inventory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory (
    id character varying(36) NOT NULL,
    material_id character varying(50) NOT NULL,
    material_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    warehouse_id character varying(36) NOT NULL,
    location_id character varying(36),
    batch_code character varying(50),
    total_qty integer NOT NULL,
    available_qty integer NOT NULL,
    reserved_qty integer,
    unit_cost numeric(10,2),
    status character varying(20),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    last_movement_at timestamp without time zone,
    material_name character varying(100),
    unit character varying(20) DEFAULT 'pcs'::character varying,
    safety_stock integer DEFAULT 10,
    reorder_point integer DEFAULT 20,
    reorder_qty integer DEFAULT 50,
    abc_class character varying(5) DEFAULT 'C'::character varying,
    location_code character varying(50),
    expiry_date date,
    storage_location character varying(100),
    qualified_status character varying(20),
    lock_reason character varying(200),
    locked_at timestamp without time zone,
    locked_by character varying(50),
    shelf_life_days integer,
    production_date date
);


--
-- Name: inventory_count_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory_count_items (
    id character varying(36) NOT NULL,
    count_id character varying(36) NOT NULL,
    inventory_id character varying(36),
    material_id character varying(50) NOT NULL,
    batch_code character varying(50),
    system_qty integer NOT NULL,
    counted_qty integer,
    diff_qty integer,
    adjusted boolean DEFAULT false,
    remark character varying(200),
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: inventory_counts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory_counts (
    id character varying(36) NOT NULL,
    count_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    warehouse_id character varying(36) NOT NULL,
    count_type character varying(20) DEFAULT 'periodic'::character varying,
    status character varying(20) DEFAULT 'draft'::character varying,
    planned_date date,
    counted_by character varying(50),
    approved_by character varying(50),
    total_items integer DEFAULT 0,
    diff_items integer DEFAULT 0,
    total_diff_qty integer DEFAULT 0,
    remark text,
    created_at timestamp without time zone DEFAULT now(),
    completed_at timestamp without time zone,
    created_by character varying(50),
    updated_by character varying(50),
    updated_at timestamp without time zone,
    variance_summary jsonb
);


--
-- Name: inventory_freezes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory_freezes (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    inventory_id character varying(36) NOT NULL,
    material_id character varying(50) NOT NULL,
    material_code character varying(50),
    batch_code character varying(50),
    reason_code character varying(50) NOT NULL,
    reason_text character varying(500),
    freeze_until timestamp without time zone,
    status character varying(20) DEFAULT 'active'::character varying,
    frozen_by character varying(50),
    unfrozen_by character varying(50),
    unfrozen_at timestamp without time zone,
    auto_unfreeze boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT now(),
    prior_status character varying(20)
);


--
-- Name: inventory_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory_transactions (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    inventory_id character varying(36),
    material_id character varying(50) NOT NULL,
    batch_code character varying(50),
    transaction_type character varying(20) NOT NULL,
    quantity integer NOT NULL,
    before_qty integer,
    after_qty integer,
    reference_type character varying(30),
    reference_id character varying(36),
    operator character varying(50),
    remark character varying(200),
    created_at timestamp without time zone DEFAULT now(),
    reference_doc_no character varying(100),
    reason_code character varying(50),
    work_order_id character varying(50),
    created_by character varying(50),
    updated_by character varying(50)
);


--
-- Name: invoice_matching; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invoice_matching (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    po_code character varying(50) NOT NULL,
    gr_code character varying(50),
    supplier_id character varying(50),
    invoice_amount numeric(14,2) NOT NULL,
    po_amount numeric(14,2) NOT NULL,
    gr_amount numeric(14,2) DEFAULT 0,
    diff_amount numeric(14,2) DEFAULT 0,
    status character varying(20) DEFAULT 'pending'::character varying,
    match_type character varying(30),
    checked_by character varying(50),
    checked_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: item_traceability; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_traceability (
    id character varying(36) NOT NULL,
    item_code character varying(50) NOT NULL,
    item_type character varying(20),
    factory_id character varying(50) NOT NULL,
    work_order_id character varying(36),
    product_id character varying(36),
    material_batch_id character varying(50),
    material_supplier_id character varying(50),
    station_id character varying(50),
    equipment_id character varying(36),
    operator_id character varying(50),
    quality_check_result character varying(20),
    serial_number character varying(50),
    next_item_code character varying(36),
    inspection_record_id character varying(36),
    metadata jsonb,
    created_by character varying(50),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: job_card_time_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_card_time_logs (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    work_order_id character varying(36),
    operation_seq integer,
    operation_name character varying(100),
    station_id character varying(50),
    operator character varying(50),
    start_time timestamp without time zone NOT NULL,
    end_time timestamp without time zone,
    duration_minutes double precision,
    completed_qty integer DEFAULT 0,
    status character varying(20) DEFAULT 'running'::character varying,
    remark character varying(200),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: job_dispatches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_dispatches (
    id character varying(36) NOT NULL,
    work_order_id character varying(36) NOT NULL,
    routing_step_id character varying(36) NOT NULL,
    operator_id character varying(36) NOT NULL,
    station_id character varying(36) NOT NULL,
    shift character varying(20) NOT NULL,
    scheduled_date character varying(10) NOT NULL,
    dispatched_by character varying(50) NOT NULL,
    status character varying(20) NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: kanban_systems; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kanban_systems (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    kanban_id character varying(50) NOT NULL,
    kanban_type character varying(50),
    upstream_station character varying(50),
    downstream_station character varying(50),
    product_id character varying(50),
    part_number character varying(100),
    min_stock_level integer,
    max_stock_level integer,
    max_card_count integer,
    current_card_count integer,
    safety_stock_level integer,
    card_status character varying(20),
    last_used_at timestamp without time zone,
    reorder_quantity integer,
    lead_time_days integer,
    kanban_card_image_url character varying(500),
    trigger_rule_type character varying(50),
    min_max_stock_levels_detail jsonb,
    holder_id character varying(50),
    status character varying(20),
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: lg_stock; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lg_stock (
    material_id character varying(100)
);


--
-- Name: lg_stock_agg; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lg_stock_agg (
    material_id character varying(100),
    qty numeric,
    val numeric
);


--
-- Name: line_balance_analyses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.line_balance_analyses (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_id character varying(50) NOT NULL,
    line_id character varying(50) NOT NULL,
    analysis_date timestamp without time zone NOT NULL,
    takt_time_min double precision,
    cycle_time_max double precision,
    cycle_time_avg double precision,
    balance_rate double precision,
    idle_time_total double precision,
    workstation_count integer,
    is_balanced boolean,
    workstation_details json,
    bottleneck_station character varying(50),
    bottleneck_time double precision,
    recommendations json,
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: line_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.line_profiles (
    id character varying(64) NOT NULL,
    factory_id character varying(64) NOT NULL,
    line_code character varying(64) NOT NULL,
    line_name character varying(128),
    hours_per_day numeric(6,2) NOT NULL,
    units_per_day numeric(10,2) NOT NULL,
    crew_size integer NOT NULL,
    parallel_lines integer DEFAULT 1 NOT NULL,
    can_make_models text[] DEFAULT '{}'::text[] NOT NULL,
    cannot_make_models text[] DEFAULT '{}'::text[] NOT NULL,
    default_model character varying(64),
    source character varying(256) NOT NULL,
    note text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    line_group character varying(64),
    group_units_per_day numeric(10,2)
);


--
-- Name: TABLE line_profiles; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.line_profiles IS '产线级物理约束：节拍、班组人数、机种兼容（单向兼容 = can/cannot 两列），推演与人挪移的依据';


--
-- Name: COLUMN line_profiles.line_group; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.line_profiles.line_group IS '同一组内的线共用一个合流产能（group_units_per_day），不是各自独立相加';


--
-- Name: COLUMN line_profiles.group_units_per_day; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.line_profiles.group_units_per_day IS '这一组一天实际能出多少台（合并值；空=按各线相加）';


--
-- Name: locations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.locations (
    id character varying(36) NOT NULL,
    location_code character varying(50) NOT NULL,
    location_name character varying(100),
    warehouse_id character varying(36) NOT NULL,
    location_type character varying(20),
    zone character varying(50),
    capacity integer,
    status character varying(20),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    aisle character varying(30),
    rack character varying(30),
    level character varying(30),
    bin_code character varying(30),
    row_num integer,
    col_num integer,
    level_num integer,
    occupancy_status character varying(20) DEFAULT 'idle'::character varying,
    "row" integer,
    "column" integer
);


--
-- Name: logic_chain_execution_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.logic_chain_execution_log (
    id character varying(36) NOT NULL,
    chain_id character varying(36),
    triggered_by character varying(50),
    trigger_payload jsonb DEFAULT '{}'::jsonb,
    conditions_matched boolean DEFAULT true,
    actions_executed jsonb DEFAULT '[]'::jsonb,
    action_results jsonb DEFAULT '[]'::jsonb,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: login_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.login_attempts (
    id bigint NOT NULL,
    username text NOT NULL,
    client_ip text,
    reason text,
    attempted_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: login_attempts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.login_attempts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: login_attempts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.login_attempts_id_seq OWNED BY public.login_attempts.id;


--
-- Name: maintenance_checklist; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_checklist (
    id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    seq integer DEFAULT 1,
    item_name character varying(200) NOT NULL,
    category character varying(30),
    standard_value character varying(100),
    measured_value character varying(100),
    is_normal boolean,
    remark character varying(200),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: maintenance_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_orders (
    id character varying(36) NOT NULL,
    order_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    equipment_id character varying(36) NOT NULL,
    maintenance_type character varying(20) NOT NULL,
    priority character varying(10) DEFAULT 'medium'::character varying,
    status character varying(20) DEFAULT 'open'::character varying,
    description text,
    planned_date timestamp without time zone,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    assigned_to character varying(50),
    result_summary text,
    downtime_minutes double precision DEFAULT 0,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    order_type character varying(50),
    scheduled_start timestamp without time zone,
    scheduled_end timestamp without time zone,
    actual_start timestamp without time zone,
    actual_end timestamp without time zone,
    parts_used jsonb,
    labor_hours double precision,
    cost_analysis jsonb,
    failure_root_cause_code character varying(50),
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: maintenance_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_plans (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    equipment_id character varying(36) NOT NULL,
    plan_name character varying(100) NOT NULL,
    frequency_days integer NOT NULL,
    last_executed_at timestamp without time zone,
    next_due_at timestamp without time zone,
    checklist text,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    plan_code character varying(50),
    plan_type character varying(50),
    frequency character varying(50),
    next_run_date date,
    last_run_date date,
    description text,
    created_by character varying(50),
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: maintenance_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_tasks (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    task_code character varying(50) NOT NULL,
    task_type character varying(20) NOT NULL,
    priority character varying(20) DEFAULT 'medium'::character varying,
    equipment_id character varying(50) NOT NULL,
    equipment_name character varying(100),
    station_id character varying(50),
    planned_date date,
    planned_duration_minutes integer DEFAULT 60,
    frequency_days integer,
    status character varying(20) DEFAULT 'pending'::character varying,
    assigned_to character varying(50),
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    actual_duration_minutes integer,
    result character varying(20),
    findings text,
    parts_used text,
    cost double precision DEFAULT 0,
    source character varying(30) DEFAULT 'manual'::character varying,
    remark text,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: material_volume_specs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.material_volume_specs (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    material_id character varying(50) NOT NULL,
    material_code character varying(50) NOT NULL,
    material_name character varying(100),
    length_cm numeric(10,2),
    width_cm numeric(10,2),
    height_cm numeric(10,2),
    unit_volume_m3 numeric(14,6) DEFAULT 0 NOT NULL,
    unit_weight_kg numeric(14,4) DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: materials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.materials (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    material_code character varying(50) NOT NULL,
    material_name character varying(200),
    unit character varying(20) DEFAULT 'pcs'::character varying,
    material_type character varying(20) DEFAULT 'purchased'::character varying,
    lead_time_days integer DEFAULT 7,
    safety_stock integer DEFAULT 0,
    moq integer DEFAULT 100,
    lot_sizing character varying(20) DEFAULT 'FOQ'::character varying,
    scrap_rate numeric(6,4) DEFAULT 0,
    default_supplier character varying(200),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    make_or_buy character varying(10) DEFAULT '外购'::character varying
);


--
-- Name: method_studies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.method_studies (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_id character varying(50) NOT NULL,
    original_operation character varying(255),
    version character varying(20),
    is_basement_method boolean,
    is_optimal_method boolean,
    description text,
    old_method_description text,
    improved_method_diagram_url character varying(500),
    expected_time_saving_calculation_detail jsonb,
    improved_operation text,
    action_sequence jsonb,
    required_resources jsonb,
    setup_time_min double precision,
    cycle_time_min double precision,
    total_standard_time_min double precision,
    validity_start timestamp without time zone,
    validity_end timestamp without time zone,
    approved_by character varying(50),
    status character varying(20),
    expected_time_saving_min double precision,
    cost_impact double precision,
    implementation_status character varying(50),
    implementer_id character varying(50),
    implementation_date timestamp without time zone,
    verification_result character varying(100),
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: mrp_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mrp_items (
    id character varying(36) NOT NULL,
    mrp_result_id character varying(36) NOT NULL,
    material_id character varying(50) NOT NULL,
    material_code character varying(50),
    material_name character varying(200),
    required_qty numeric(18,4) DEFAULT 0 NOT NULL,
    available_qty numeric(18,4) DEFAULT 0,
    reserved_qty numeric(18,4) DEFAULT 0,
    on_order_qty numeric(18,4) DEFAULT 0,
    shortage_qty numeric(18,4) DEFAULT 0,
    unit character varying(20),
    unit_cost numeric(18,4),
    created_at timestamp without time zone DEFAULT now(),
    level integer,
    parent_code character varying(100),
    allocated_qty numeric(18,4) DEFAULT 0 NOT NULL,
    item_type character varying(10)
);


--
-- Name: mrp_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mrp_results (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    plan_id character varying(36) NOT NULL,
    calculated_at timestamp without time zone DEFAULT now(),
    target_date date,
    status character varying(20) DEFAULT 'pending'::character varying,
    total_required numeric(18,4),
    total_available numeric(18,4),
    total_shortage numeric(18,4),
    total_value numeric(18,2),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: mrp_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mrp_runs (
    id character varying(80) NOT NULL,
    factory_id character varying(50) NOT NULL,
    plan_ids text NOT NULL,
    plan_codes text NOT NULL,
    product_name text,
    status character varying(20) DEFAULT 'calculated'::character varying,
    summary jsonb,
    items jsonb,
    planned_orders jsonb,
    exceptions jsonb,
    weekly jsonb,
    calculated_at timestamp without time zone DEFAULT now()
);


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    recipient character varying(50),
    category character varying(30) DEFAULT 'system'::character varying NOT NULL,
    title character varying(200) NOT NULL,
    content text,
    severity character varying(10) DEFAULT 'info'::character varying,
    source_type character varying(30),
    source_id character varying(50),
    is_read boolean DEFAULT false,
    read_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    created_by character varying(50),
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: oee_daily; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oee_daily (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    equipment_id character varying(50) NOT NULL,
    snapshot_date date NOT NULL,
    planned_production_minutes double precision DEFAULT 0,
    actual_run_minutes double precision DEFAULT 0,
    downtime_minutes double precision DEFAULT 0,
    availability double precision DEFAULT 0,
    performance double precision DEFAULT 0,
    quality double precision DEFAULT 0,
    oee double precision DEFAULT 0,
    planned_output integer DEFAULT 0,
    actual_output integer DEFAULT 0,
    good_output integer DEFAULT 0,
    breakdown_minutes double precision DEFAULT 0,
    setup_minutes double precision DEFAULT 0,
    idle_minutes double precision DEFAULT 0,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: office_positions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.office_positions (
    id character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    position_code character varying(30) NOT NULL,
    position_name character varying(60) NOT NULL,
    department_id character varying(50),
    department_name character varying(60),
    needs_computer boolean DEFAULT true,
    employee_id character varying(50),
    employee_name character varying(50),
    status character varying(20) DEFAULT 'active'::character varying,
    shift character varying(10) DEFAULT '白班'::character varying,
    remark character varying(100),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: online_workbooks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.online_workbooks (
    id character varying(36) NOT NULL,
    name character varying(255) NOT NULL,
    factory_id character varying(50),
    snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    source_file_id character varying(36),
    created_by character varying(50),
    updated_by character varying(50),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: operators; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operators (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    employee_id character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    dept_id character varying(36),
    team_id character varying(36),
    skills json,
    status character varying(20) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: orchestration_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orchestration_logs (
    id character varying(36) NOT NULL,
    factory_id character varying(50),
    intent character varying(100),
    intent_name character varying(100),
    status character varying(20),
    sub_tasks text,
    synthesis text,
    total_duration_ms integer,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: order_decomposition_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.order_decomposition_logs (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    sales_order_id character varying(36) NOT NULL,
    action character varying(30) NOT NULL,
    result text,
    work_orders_created integer DEFAULT 0,
    operator character varying(50),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: org_units; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.org_units (
    id character varying(36) NOT NULL,
    code character varying(50),
    name character varying(200),
    parent_id character varying(36),
    level_type character varying(20) DEFAULT 'operational'::character varying,
    factory_id character varying(50),
    metadata_ jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: outbound_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outbound_orders (
    id character varying(36) NOT NULL,
    outbound_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    warehouse_id character varying(36) NOT NULL,
    material_id character varying(50) NOT NULL,
    quantity integer NOT NULL,
    work_order_id character varying(50),
    batch_code character varying(50),
    outbound_type character varying(20),
    status character varying(20),
    created_by character varying(50),
    created_at timestamp without time zone NOT NULL,
    completed_at timestamp without time zone,
    sales_order_id character varying(50)
);


--
-- Name: parameter_change_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parameter_change_audit (
    id character varying(36) NOT NULL,
    param_id character varying(36),
    from_value character varying,
    to_value character varying,
    changed_by character varying(50),
    changed_at timestamp without time zone DEFAULT now(),
    reason text,
    approval_required boolean DEFAULT false,
    approval_status character varying(20) DEFAULT 'auto_approved'::character varying,
    approval_record_id character varying(36),
    source character varying(20) DEFAULT 'panel'::character varying,
    impact_summary text
);


--
-- Name: payment_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payment_requests (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    payment_code character varying(50) NOT NULL,
    supplier_id character varying(50),
    supplier_name character varying(200),
    po_code character varying(50),
    amount numeric(14,2) NOT NULL,
    due_date date,
    status character varying(20) DEFAULT 'pending'::character varying,
    payment_method character varying(50) DEFAULT '银行转账'::character varying,
    remark character varying(500),
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.permissions (
    id character varying(36) NOT NULL,
    module character varying(50) NOT NULL,
    action character varying(30) NOT NULL,
    module_name character varying(50),
    action_name character varying(50),
    description text,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: personal_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.personal_decisions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    factory_id character varying(50) NOT NULL,
    employee_id character varying(50) NOT NULL,
    decision_type character varying(50) NOT NULL,
    situation text NOT NULL,
    decision text NOT NULL,
    reasoning text,
    outcome text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: personal_knowledge; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.personal_knowledge (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    factory_id character varying(50) NOT NULL,
    employee_id character varying(50) NOT NULL,
    category character varying(20) DEFAULT 'tip'::character varying NOT NULL,
    title character varying(200) NOT NULL,
    content text NOT NULL,
    tags jsonb DEFAULT '[]'::jsonb,
    source character varying(30) DEFAULT 'manual'::character varying,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: pick_list_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pick_list_items (
    id character varying(36) NOT NULL,
    pick_list_id character varying(36) NOT NULL,
    material_id character varying(50) NOT NULL,
    material_name character varying(100),
    required_qty integer NOT NULL,
    picked_qty integer DEFAULT 0,
    batch_code character varying(50),
    location character varying(50),
    status character varying(20) DEFAULT 'pending'::character varying,
    remark character varying(200)
);


--
-- Name: pick_lists; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pick_lists (
    id character varying(36) NOT NULL,
    pick_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    work_order_id character varying(36),
    work_order_code character varying(50),
    status character varying(20) DEFAULT 'draft'::character varying,
    warehouse_id character varying(36),
    total_items integer DEFAULT 0,
    picked_items integer DEFAULT 0,
    picked_by character varying(50),
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: plan_change_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.plan_change_requests (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    plan_id character varying(50) NOT NULL,
    plan_code character varying(50),
    applicant character varying(50),
    change_type character varying(20) DEFAULT 'update'::character varying,
    changes jsonb,
    description text,
    status character varying(20) DEFAULT 'pending'::character varying,
    impact_analysis jsonb,
    approved_by character varying(50),
    reason text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.plans (
    id character varying(36) NOT NULL,
    plan_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_id character varying(50) NOT NULL,
    sales_order_id character varying(50),
    quantity integer NOT NULL,
    required_date timestamp without time zone NOT NULL,
    plan_type character varying(20) NOT NULL,
    customer_level character varying(10) NOT NULL,
    priority integer NOT NULL,
    status character varying(20) NOT NULL,
    due_date timestamp without time zone,
    priority_score double precision NOT NULL,
    confirmed_by character varying(50),
    confirmed_at timestamp without time zone,
    released_by character varying(50),
    released_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    created_by character varying(50)
);


--
-- Name: pmc_changes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmc_changes (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    change_type character varying(30) NOT NULL,
    target_type character varying(20) NOT NULL,
    target_code character varying(50) NOT NULL,
    before_value character varying(200),
    after_value character varying(200),
    reason character varying(300),
    impact_summary character varying(500),
    created_by character varying(50) DEFAULT 'pmc_agent'::character varying,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: pmc_knowledge; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmc_knowledge (
    id character varying(36) NOT NULL,
    category character varying(20) NOT NULL,
    seq integer NOT NULL,
    title character varying(200) NOT NULL,
    content text NOT NULL,
    tags text DEFAULT ''::text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: pmc_quiz_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmc_quiz_attempts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id character varying(64) NOT NULL,
    factory_id character varying(64),
    answers jsonb DEFAULT '{}'::jsonb NOT NULL,
    score numeric(5,2) DEFAULT 0 NOT NULL,
    earned_points integer DEFAULT 0 NOT NULL,
    total_points integer DEFAULT 0 NOT NULL,
    details jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: pmc_quiz_questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmc_quiz_questions (
    id character varying(64) NOT NULL,
    question_code character varying(64) NOT NULL,
    skill character varying(64) NOT NULL,
    difficulty integer DEFAULT 1 NOT NULL,
    question_type character varying(16) DEFAULT 'single'::character varying NOT NULL,
    prompt text NOT NULL,
    options jsonb DEFAULT '[]'::jsonb NOT NULL,
    answer jsonb DEFAULT '[]'::jsonb NOT NULL,
    explanation text NOT NULL,
    reference_terms jsonb DEFAULT '[]'::jsonb NOT NULL,
    points integer DEFAULT 1 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: pmc_trainer_actions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmc_trainer_actions (
    id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    task_type character varying(30) NOT NULL,
    task_ref character varying(100),
    action character varying(30),
    payload text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: pmc_trainer_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmc_trainer_sessions (
    id character varying(36) NOT NULL,
    user_id character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying,
    started_at timestamp without time zone DEFAULT now(),
    completed_at timestamp without time zone,
    tasks_json text,
    report_json text
);


--
-- Name: position_capabilities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.position_capabilities (
    id character varying(36) DEFAULT gen_random_uuid() NOT NULL,
    cap_code character varying(50),
    cap_name character varying(200),
    skill_level_min character varying(10),
    skill_level_max character varying(10),
    org_unit_id character varying(36),
    description text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: position_sops; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.position_sops (
    id integer NOT NULL,
    position_code character varying(64) NOT NULL,
    industry_code character varying(64) DEFAULT 'generic'::character varying NOT NULL,
    title character varying(255) NOT NULL,
    duties text,
    daily_flow jsonb,
    escalation_path jsonb,
    related_tools jsonb,
    extra jsonb,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: position_sops_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.position_sops_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: position_sops_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.position_sops_id_seq OWNED BY public.position_sops.id;


--
-- Name: position_training_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.position_training_attempts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    position_code character varying(64) NOT NULL,
    user_id character varying(64) NOT NULL,
    factory_id character varying(64),
    answers jsonb DEFAULT '{}'::jsonb NOT NULL,
    score numeric(5,2) DEFAULT 0 NOT NULL,
    earned_points integer DEFAULT 0 NOT NULL,
    total_points integer DEFAULT 0 NOT NULL,
    details jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: position_training_questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.position_training_questions (
    id character varying(64) NOT NULL,
    position_code character varying(64) NOT NULL,
    question_code character varying(64) NOT NULL,
    skill character varying(64) NOT NULL,
    difficulty integer DEFAULT 1 NOT NULL,
    question_type character varying(16) DEFAULT 'single'::character varying NOT NULL,
    prompt text NOT NULL,
    options jsonb DEFAULT '[]'::jsonb NOT NULL,
    answer jsonb DEFAULT '[]'::jsonb NOT NULL,
    explanation text NOT NULL,
    reference_terms jsonb DEFAULT '[]'::jsonb NOT NULL,
    points integer DEFAULT 1 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: pp_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pp_plans (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    plan_code character varying(50) NOT NULL,
    plan_type character varying(20) NOT NULL,
    product_id character varying(50) NOT NULL,
    sales_order_id character varying(50),
    quantity integer NOT NULL,
    required_date date NOT NULL,
    due_date date,
    customer_level character varying(10),
    priority integer,
    priority_score numeric(10,2),
    status character varying(20) NOT NULL,
    planning_cycle character varying(30),
    release_status character varying(20),
    planner_id character varying(50),
    station_id character varying(50),
    scheduled_start_date date,
    scheduled_end_date date,
    mrp_status character varying(20),
    created_by character varying(50),
    updated_by character varying(50),
    confirmed_by character varying(50),
    released_by character varying(50),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    confirmed_at timestamp without time zone,
    released_at timestamp without time zone,
    work_order_id character varying(36),
    cancelled_by character varying(50),
    cancelled_at timestamp without time zone,
    completed_by character varying(50),
    update_reason text
);


--
-- Name: process_analyses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.process_analyses (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_id character varying(50) NOT NULL,
    operation_code character varying(50) NOT NULL,
    analysis_date timestamp without time zone NOT NULL,
    total_process_time_min double precision,
    va_time_min double precision,
    nva_time_min double precision,
    wait_time_min double precision,
    move_time_min double precision,
    inspect_time_min double precision,
    va_ratio double precision,
    lead_time double precision,
    efficiency_score double precision,
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: process_capability; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.process_capability (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_id character varying(50) NOT NULL,
    station_id character varying(50) NOT NULL,
    operation_name character varying(100),
    characteristic character varying(100),
    specification_min double precision,
    specification_max double precision,
    mean_value double precision,
    standard_deviation double precision,
    cp double precision,
    cpk double precision,
    sampling_size integer,
    sample_date timestamp without time zone NOT NULL,
    status character varying(20),
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: process_performance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.process_performance (
    id character varying(36) NOT NULL,
    work_order_id character varying(36) NOT NULL,
    routing_step_id character varying(36) NOT NULL,
    station_id character varying(50) NOT NULL,
    operator_id character varying(50) NOT NULL,
    dept_id character varying(36),
    team_id character varying(36),
    planned_cycle_time integer NOT NULL,
    actual_cycle_time integer NOT NULL,
    start_time timestamp without time zone NOT NULL,
    end_time timestamp without time zone,
    produced_qty integer NOT NULL,
    good_qty integer NOT NULL,
    efficiency_rate double precision NOT NULL,
    yield_rate double precision NOT NULL,
    idle_time integer NOT NULL,
    anomaly_flags json,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: production_alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.production_alerts (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    alert_type character varying(30) NOT NULL,
    severity character varying(10) DEFAULT 'warning'::character varying NOT NULL,
    title character varying(200) NOT NULL,
    message text,
    source_type character varying(30),
    source_id character varying(50),
    metric_value double precision,
    threshold_value double precision,
    is_read boolean DEFAULT false,
    is_resolved boolean DEFAULT false,
    resolved_by character varying(50),
    resolved_at timestamp without time zone,
    triggered_at timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now(),
    created_by character varying(50),
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: production_alerts_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.production_alerts_archive (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    alert_type character varying(30) NOT NULL,
    severity character varying(10) DEFAULT 'warning'::character varying NOT NULL,
    title character varying(200) NOT NULL,
    message text,
    source_type character varying(30),
    source_id character varying(50),
    metric_value double precision,
    threshold_value double precision,
    is_read boolean DEFAULT false,
    is_resolved boolean DEFAULT false,
    resolved_by character varying(50),
    resolved_at timestamp without time zone,
    triggered_at timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now(),
    created_by character varying(50),
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: production_report_comments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.production_report_comments (
    id character varying(36) NOT NULL,
    report_id character varying(36) NOT NULL,
    comment text NOT NULL,
    created_by character varying(50),
    created_at timestamp without time zone NOT NULL
);


--
-- Name: production_reports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.production_reports (
    id character varying(36) NOT NULL,
    report_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    work_order_id character varying(36) NOT NULL,
    station_id character varying(50) NOT NULL,
    good_qty integer NOT NULL,
    defect_qty integer,
    scrap_qty integer,
    report_type character varying(20),
    shift character varying(20),
    operator_id character varying(50),
    remark text,
    is_modified boolean,
    modified_at timestamp without time zone,
    modified_by character varying(50),
    created_by character varying(50),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    operation_seq integer,
    operation_name character varying(100),
    machine_id character varying(50),
    start_time timestamp without time zone,
    end_time timestamp without time zone,
    cycle_time_sec double precision,
    is_undone boolean DEFAULT false,
    undone_at timestamp without time zone,
    undone_by character varying(50),
    assistant_operator_ids jsonb,
    quality_check_passed boolean,
    batch_code character varying(50),
    tool_id character varying(36),
    operator_skill_level character varying(20),
    qc_gate_passed boolean DEFAULT true,
    material_batch_code character varying(50),
    CONSTRAINT check_pr_defect_non_negative CHECK ((defect_qty >= 0)),
    CONSTRAINT check_pr_good_non_negative CHECK ((good_qty >= 0)),
    CONSTRAINT check_pr_scrap_non_negative CHECK ((scrap_qty >= 0)),
    CONSTRAINT check_pr_total_non_negative CHECK ((((good_qty + defect_qty) + scrap_qty) >= 0))
);


--
-- Name: COLUMN production_reports.batch_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.production_reports.batch_code IS 'Raw material batch code for quality traceability; links to incoming quality inspection';


--
-- Name: COLUMN production_reports.tool_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.production_reports.tool_id IS 'Tool/fixture ID used in this operation; enables tool wear analysis and replacement scheduling';


--
-- Name: COLUMN production_reports.operator_skill_level; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.production_reports.operator_skill_level IS 'Operator skill level (e.g., "Junior", "Senior", "Certified"); correlates with yield rate and defect analysis';


--
-- Name: COLUMN production_reports.qc_gate_passed; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.production_reports.qc_gate_passed IS 'QC gate passed flag; critical control point verification before reporting completion';


--
-- Name: COLUMN production_reports.material_batch_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.production_reports.material_batch_code IS 'Material batch code from BOM consumption; distinct from product batch for multi-batch production runs';


--
-- Name: CONSTRAINT check_pr_defect_non_negative ON production_reports; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON CONSTRAINT check_pr_defect_non_negative ON public.production_reports IS 'Prevents negative defect quantity entry';


--
-- Name: CONSTRAINT check_pr_good_non_negative ON production_reports; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON CONSTRAINT check_pr_good_non_negative ON public.production_reports IS 'Prevents negative good quantity entry';


--
-- Name: CONSTRAINT check_pr_scrap_non_negative ON production_reports; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON CONSTRAINT check_pr_scrap_non_negative ON public.production_reports IS 'Prevents negative scrap quantity entry';


--
-- Name: CONSTRAINT check_pr_total_non_negative ON production_reports; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON CONSTRAINT check_pr_total_non_negative ON public.production_reports IS 'Ensures total reported quantity is non-negative';


--
-- Name: products; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.products (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_code character varying(50) NOT NULL,
    product_name character varying(100) NOT NULL,
    category character varying(50) NOT NULL,
    unit character varying(20) NOT NULL,
    description character varying(500),
    status character varying(20) NOT NULL,
    standard_cost double precision,
    selling_price double precision,
    current_bom_version character varying(20),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    created_by character varying(50),
    current_routing_id character varying(50),
    engineering_lead_time_days double precision,
    manufacturing_lead_time_days double precision
);


--
-- Name: program_work_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.program_work_orders (
    id character varying(50) NOT NULL,
    factory_id character varying(50),
    pwo_code character varying(50) NOT NULL,
    template_code character varying(50) NOT NULL,
    template_name character varying(120),
    module character varying(30),
    title character varying(300) NOT NULL,
    priority character varying(20) DEFAULT 'medium'::character varying,
    status character varying(20) DEFAULT 'open'::character varying,
    form_data jsonb DEFAULT '{}'::jsonb,
    source_ticket_id character varying(50),
    created_by character varying(80),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    closed_at timestamp without time zone,
    closed_by character varying(80)
);


--
-- Name: pull_replenishment_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pull_replenishment_tasks (
    id character varying(36) NOT NULL,
    task_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    source_warehouse_id character varying(36),
    target_location_id character varying(36),
    material_id character varying(50) NOT NULL,
    requested_qty integer NOT NULL,
    fulfilled_qty integer NOT NULL,
    status character varying(20),
    trigger_type character varying(20),
    work_order_id character varying(36),
    threshold_id character varying(36),
    assigned_to character varying(50),
    created_by character varying(50),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    completed_at timestamp without time zone
);


--
-- Name: purchase_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.purchase_orders (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    po_code character varying(50) NOT NULL,
    pr_id character varying(36),
    supplier_id character varying(36),
    supplier_name character varying(200),
    material_code character varying(50) NOT NULL,
    material_name character varying(200),
    qty numeric(12,3) NOT NULL,
    unit_price numeric(12,4),
    total_amount numeric(14,2),
    currency character varying(10) DEFAULT 'CNY'::character varying,
    order_date date DEFAULT CURRENT_DATE,
    expected_date date,
    actual_date date,
    status character varying(20) DEFAULT 'draft'::character varying,
    auto_generated boolean DEFAULT false,
    created_by character varying(50) DEFAULT 'system'::character varying,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    received_qty numeric DEFAULT 0,
    tax_rate numeric,
    payment_terms character varying(50),
    contract_no character varying(50),
    delivery_address character varying(200),
    supplier_contact character varying(80)
);


--
-- Name: purchase_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.purchase_requests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    factory_id character varying(50) NOT NULL,
    material_code character varying(100) NOT NULL,
    material_name character varying(200),
    requested_qty numeric DEFAULT 0 NOT NULL,
    unit character varying(20) DEFAULT 'pcs'::character varying,
    urgency character varying(20) DEFAULT 'normal'::character varying,
    status character varying(20) DEFAULT 'pending'::character varying,
    source character varying(50) DEFAULT 'warehouse_agent'::character varying,
    supplier_id character varying(50),
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: purchase_requisitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.purchase_requisitions (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    pr_code character varying(50) NOT NULL,
    source character varying(30) DEFAULT 'mrp'::character varying,
    source_id character varying(50),
    material_code character varying(50) NOT NULL,
    material_name character varying(200),
    qty numeric(12,3) NOT NULL,
    unit character varying(20) DEFAULT 'PCS'::character varying,
    required_date date,
    status character varying(20) DEFAULT 'pending'::character varying,
    auto_approved boolean DEFAULT false,
    approved_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    purchase_code character varying(50),
    material_id character varying(50),
    required_qty integer,
    suggested_qty integer,
    shortage_qty integer,
    suggested_date timestamp without time zone,
    priority character varying(20) DEFAULT 'NORMAL'::character varying,
    mrp_plan_id character varying(36),
    estimated_cost numeric(15,2),
    supplier_id character varying(50),
    lead_time_days integer,
    created_by character varying(50),
    approved_at timestamp without time zone,
    rejection_reason text,
    approved_comment text
);


--
-- Name: purchase_returns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.purchase_returns (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    return_code character varying(50) NOT NULL,
    po_code character varying(50),
    material_code character varying(100),
    quantity numeric(14,2) NOT NULL,
    reason character varying(300),
    return_type character varying(20) DEFAULT 'return'::character varying,
    status character varying(20) DEFAULT 'pending'::character varying,
    supplier_id character varying(50),
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: purchase_suggestions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.purchase_suggestions (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    mrp_item_id character varying(36),
    material_id character varying(50) NOT NULL,
    material_code character varying(50),
    material_name character varying(200),
    required_qty numeric(18,4),
    suggested_qty numeric(18,4),
    suggested_date date,
    priority character varying(20) DEFAULT 'normal'::character varying,
    estimated_cost numeric(18,2),
    supplier_id character varying(50),
    supplier_name character varying(200),
    status character varying(20) DEFAULT 'pending'::character varying,
    purchase_order_id character varying(50),
    suggested_at timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: qms_8d_reports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qms_8d_reports (
    id character varying(36) NOT NULL,
    report_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    defect_record_id character varying(36),
    title character varying(200) NOT NULL,
    severity character varying(20) DEFAULT 'major'::character varying,
    status character varying(20) DEFAULT 'open'::character varying,
    d1_team text,
    d2_problem_description text,
    d3_containment_action text,
    d4_root_cause text,
    d5_corrective_action text,
    d6_implementation text,
    d7_preventive_action text,
    d8_congratulations text,
    opened_by character varying(50),
    closed_by character varying(50),
    due_date timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    created_by character varying(50),
    updated_by character varying(50)
);


--
-- Name: qms_inspection_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qms_inspection_items (
    id character varying(36) NOT NULL,
    inspection_id character varying(36) NOT NULL,
    item_name character varying(100) NOT NULL,
    item_code character varying(50),
    spec_lower double precision,
    spec_upper double precision,
    target_value double precision,
    measured_value double precision,
    result character varying(10),
    measurement_method character varying(50),
    remark character varying(200),
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: qms_spc_points; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qms_spc_points (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    characteristic_code character varying(50) NOT NULL,
    characteristic_name character varying(100),
    work_order_id character varying(36),
    station_id character varying(50),
    measured_value double precision NOT NULL,
    sample_group integer,
    ucl double precision,
    lcl double precision,
    cl double precision,
    is_out_of_control boolean DEFAULT false,
    measured_at timestamp without time zone DEFAULT now(),
    measured_by character varying(50),
    control_chart_type character varying(30),
    calculation_method character varying(50),
    subgroup_count integer,
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: quality_costs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_costs (
    id character varying(36) NOT NULL,
    related_capa_id uuid,
    amount numeric(15,2) NOT NULL,
    currency character varying(3),
    cost_date timestamp without time zone,
    description text,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: quality_defects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_defects (
    id character varying(36) NOT NULL,
    inspection_id uuid NOT NULL,
    defect_code character varying(50),
    defect_category character varying(50),
    defect_description text,
    operation_seq integer,
    station_id character varying(50),
    quantity integer,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: quality_goal_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_goal_reviews (
    id character varying(36) NOT NULL,
    goal_id character varying(36) NOT NULL,
    review_date timestamp without time zone DEFAULT now(),
    measured_value double precision,
    gap double precision,
    status character varying(20) DEFAULT 'on_track'::character varying,
    action_plan text,
    reviewed_by character varying(50),
    remark character varying(500),
    reviewer character varying(50),
    comments text,
    approved boolean,
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: quality_goals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_goals (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    goal_code character varying(50) NOT NULL,
    goal_name character varying(200) NOT NULL,
    metric_type character varying(30) NOT NULL,
    target_value double precision NOT NULL,
    current_value double precision,
    unit character varying(20) DEFAULT '%'::character varying,
    period character varying(20) DEFAULT 'monthly'::character varying,
    responsible character varying(50),
    status character varying(20) DEFAULT 'active'::character varying,
    review_frequency_days integer DEFAULT 30,
    last_reviewed_at timestamp without time zone,
    next_review_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    product_id character varying(50),
    actual_value double precision,
    created_by character varying(50),
    updated_by character varying(50)
);


--
-- Name: quality_inspections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_inspections (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    work_order_id character varying(36) NOT NULL,
    routing_step_id character varying(36) NOT NULL,
    inspect_type character varying(20) NOT NULL,
    inspector_id character varying(50) NOT NULL,
    sample_qty integer NOT NULL,
    defect_qty integer NOT NULL,
    result character varying(20) NOT NULL,
    defect_details json,
    remark character varying(500),
    created_at timestamp without time zone NOT NULL,
    inspection_phase character varying(30),
    sampling_method character varying(100),
    check_tool_id character varying(50),
    hold_status character varying(20) DEFAULT NULL::character varying
);


--
-- Name: quality_red_tag; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_red_tag (
    id character varying(36) NOT NULL,
    factory_id character varying(36) NOT NULL,
    red_tag_no character varying(50) NOT NULL,
    defect_id character varying(36) NOT NULL,
    inspection_id character varying(36),
    red_tag_type character varying(20) NOT NULL,
    defect_description text,
    nonconforming_qty numeric(12,4) NOT NULL,
    batch_no character varying(100),
    work_order_id character varying(36),
    station_id character varying(36),
    discovered_by character varying(36),
    discovered_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    severity character varying(20) DEFAULT 'MINOR'::character varying,
    quarantine_status character varying(20) DEFAULT 'SEATED'::character varying,
    disposition character varying(20),
    disposition_by character varying(36),
    disposition_date timestamp without time zone,
    disposition_notes text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    is_deleted boolean DEFAULT false,
    created_by character varying(36)
);


--
-- Name: quality_red_tag_attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_red_tag_attachments (
    id character varying(36) NOT NULL,
    red_tag_id character varying(36) NOT NULL,
    file_id character varying(36) NOT NULL,
    attachment_type character varying(20) DEFAULT 'PHOTO'::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: quotations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotations (
    id character varying(36) NOT NULL,
    rfq_id character varying(36) NOT NULL,
    supplier_id character varying(50) NOT NULL,
    supplier_name character varying(200),
    unit_price numeric(14,2) NOT NULL,
    lead_time_days integer NOT NULL,
    delivery_date date,
    payment_terms character varying(100),
    status character varying(20) DEFAULT 'received'::character varying,
    selected_by character varying(50),
    selected_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: rcc_approval_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rcc_approval_records (
    id character varying(36) NOT NULL,
    rcc_task_id character varying(36),
    approver_role character varying(50) NOT NULL,
    approver_name character varying(100),
    decision character varying(20) NOT NULL,
    decision_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    comment text,
    escalation_level integer DEFAULT 0
);


--
-- Name: rcc_decision_evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rcc_decision_evaluations (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    rcc_task_id character varying(36),
    task_code character varying(50),
    action character varying(30) NOT NULL,
    target character varying(200),
    status character varying(20) DEFAULT 'tracking'::character varying NOT NULL,
    executed_at timestamp without time zone,
    approved_by character varying(50),
    expectations jsonb,
    baseline jsonb,
    latest_measure jsonb,
    verdict_note text,
    downstream_impact jsonb,
    evaluation_count integer DEFAULT 0,
    max_evaluations integer DEFAULT 8,
    next_evaluate_at timestamp without time zone,
    last_evaluated_at timestamp without time zone,
    finalized_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: rcc_organizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rcc_organizations (
    id character varying(36) NOT NULL,
    org_type character varying(20) DEFAULT 'rcc'::character varying NOT NULL,
    resource_pool jsonb DEFAULT '{}'::jsonb,
    capacity_model jsonb DEFAULT '{}'::jsonb,
    dispatch_rules jsonb DEFAULT '[]'::jsonb,
    auto_dispatch_enabled boolean DEFAULT false,
    human_approval_required boolean DEFAULT true,
    approval_threshold_pct double precision DEFAULT 80.0,
    last_sync_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: rcc_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rcc_tasks (
    id character varying(36) NOT NULL,
    task_code character varying(50) NOT NULL,
    org_unit_id character varying(36),
    task_type character varying(30) NOT NULL,
    title character varying(200) NOT NULL,
    description text,
    affected_params jsonb DEFAULT '[]'::jsonb,
    affected_entities jsonb DEFAULT '[]'::jsonb,
    expected_impact_summary text,
    status character varying(20) DEFAULT 'pending'::character varying,
    approved_by character varying(50),
    approved_at timestamp without time zone,
    rejected_by character varying(50),
    rejection_reason text,
    executed_at timestamp without time zone,
    completed_at timestamp without time zone,
    requested_by character varying(50),
    request_context jsonb DEFAULT '{}'::jsonb,
    source_ticket_id character varying(36),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    factory_id character varying(50)
);


--
-- Name: reconciliation_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reconciliation_logs (
    id character varying(36) NOT NULL,
    reconcile_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    work_order_id character varying(36),
    planned_qty integer NOT NULL,
    good_qty integer NOT NULL,
    defect_qty integer NOT NULL,
    scrap_qty integer NOT NULL,
    net_change integer NOT NULL,
    expected_delta integer NOT NULL,
    delta integer NOT NULL,
    status character varying(20) NOT NULL,
    discrepancy_detail text,
    checked_by character varying(50),
    checked_at timestamp without time zone NOT NULL
);


--
-- Name: replenishment_thresholds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.replenishment_thresholds (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    warehouse_id character varying(36),
    location_id character varying(36),
    material_id character varying(50) NOT NULL,
    min_level integer NOT NULL,
    max_level integer NOT NULL,
    safety_stock integer NOT NULL,
    reorder_lot_size integer NOT NULL,
    reorder_lead_time_hours double precision,
    line_side_location character varying(50),
    active boolean,
    created_by character varying(50),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: rfqs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rfqs (
    id character varying(36) NOT NULL,
    rfq_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    material_code character varying(100) NOT NULL,
    material_name character varying(200),
    quantity numeric(14,2) NOT NULL,
    unit character varying(20) DEFAULT 'PCS'::character varying,
    required_date date,
    status character varying(20) DEFAULT 'open'::character varying,
    created_by character varying(50) DEFAULT 'procurement_agent'::character varying,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: role_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_permissions (
    id character varying(36) NOT NULL,
    role_id character varying(36) NOT NULL,
    permission_id character varying(36) NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: role_simulation_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_simulation_profiles (
    role_code character varying(64) NOT NULL,
    display_name character varying(255) NOT NULL,
    role_family character varying(64) NOT NULL,
    speaking_style text NOT NULL,
    decision_style text NOT NULL,
    terminology jsonb DEFAULT '[]'::jsonb NOT NULL,
    evidence_requirements jsonb DEFAULT '[]'::jsonb NOT NULL,
    policy_gates jsonb DEFAULT '[]'::jsonb NOT NULL,
    allowed_actions jsonb DEFAULT '[]'::jsonb NOT NULL,
    blocked_actions jsonb DEFAULT '[]'::jsonb NOT NULL,
    tone_examples jsonb DEFAULT '[]'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id character varying(36) NOT NULL,
    role_code character varying(50) NOT NULL,
    role_name character varying(100) NOT NULL,
    "position" character varying(30) NOT NULL,
    department character varying(50),
    description text,
    is_system boolean,
    level integer,
    permissions jsonb,
    data_scope jsonb,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: routing_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.routing_steps (
    id character varying(36) NOT NULL,
    routing_id character varying(36) NOT NULL,
    dept_id character varying(36),
    sequence integer NOT NULL,
    operation_name character varying(100) NOT NULL,
    station_id character varying(50) NOT NULL,
    standard_time integer NOT NULL,
    setup_time integer NOT NULL,
    tools json,
    parameters json,
    quality_check integer NOT NULL,
    required_skills json
);


--
-- Name: routing_template_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.routing_template_steps (
    id character varying(36) NOT NULL,
    template_id character varying(36) NOT NULL,
    seq integer NOT NULL,
    process_code character varying(20) NOT NULL,
    operation_name character varying(100) NOT NULL,
    work_center character varying(20),
    standard_hours numeric(8,2) DEFAULT 0,
    is_parallel boolean DEFAULT false,
    is_qc_gate boolean DEFAULT false,
    remark text,
    created_at timestamp without time zone DEFAULT now(),
    quality_requirement text,
    sop_document_url character varying(500),
    tooling_requirement jsonb
);


--
-- Name: routing_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.routing_templates (
    id character varying(36) NOT NULL,
    template_code character varying(50) NOT NULL,
    template_name character varying(100) NOT NULL,
    factory_id character varying(50) NOT NULL,
    description text,
    is_active boolean DEFAULT true,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: routings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.routings (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_id character varying(50) NOT NULL,
    version character varying(20) NOT NULL,
    status character varying(20) NOT NULL,
    remark character varying(500),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    created_by character varying(50),
    routing_code character varying(50),
    steps jsonb DEFAULT '[]'::jsonb,
    is_active boolean DEFAULT true
);


--
-- Name: rush_order_approval_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rush_order_approval_logs (
    id character varying(36) NOT NULL,
    approval_id character varying(36) NOT NULL,
    action character varying(20) NOT NULL,
    actor character varying(50) NOT NULL,
    actor_role character varying(50),
    comment text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: rush_order_approvals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rush_order_approvals (
    id character varying(36) NOT NULL,
    approval_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_id character varying(50) NOT NULL,
    quantity integer NOT NULL,
    due_date date,
    rush_priority character varying(20) DEFAULT 'urgent'::character varying NOT NULL,
    impact_json jsonb,
    affected_orders integer DEFAULT 0,
    max_delay_days numeric(8,2) DEFAULT 0,
    process_hours numeric(10,2),
    recommendation text,
    approval_level integer DEFAULT 2 NOT NULL,
    required_role character varying(50),
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    applicant character varying(50),
    approver character varying(50),
    approved_at timestamp without time zone,
    reject_reason text,
    target_schedule_id character varying(36),
    target_wo_id character varying(36),
    executed_at timestamp without time zone,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: safety_stock_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.safety_stock_config (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    material_id character varying(50) NOT NULL,
    material_code character varying(50),
    material_name character varying(100),
    safety_stock integer DEFAULT 0,
    reorder_point integer DEFAULT 0,
    max_stock integer DEFAULT 0,
    dead_stock_days integer DEFAULT 90,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    shelf_life_days integer DEFAULT 0,
    expiry_warn_days integer DEFAULT 30,
    slow_moving_days integer DEFAULT 60
);


--
-- Name: sales_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sales_orders (
    id character varying(36) NOT NULL,
    order_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    customer_name character varying(100),
    customer_code character varying(50),
    product_id character varying(50) NOT NULL,
    product_name character varying(100),
    quantity integer DEFAULT 0 NOT NULL,
    unit character varying(20) DEFAULT 'pcs'::character varying,
    delivery_date date,
    priority character varying(20) DEFAULT 'medium'::character varying,
    status character varying(20) DEFAULT 'pending'::character varying,
    decomposed boolean DEFAULT false,
    decomposed_at timestamp without time zone,
    work_order_ids text,
    material_ready boolean DEFAULT false,
    material_check_at timestamp without time zone,
    unit_price double precision,
    total_amount double precision,
    currency character varying(10) DEFAULT 'CNY'::character varying,
    remark text,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    ship_date date,
    review_status character varying(32),
    committed_delivery date,
    risk_level character varying(16),
    review_note text,
    reviewed_by character varying(64),
    reviewed_at timestamp without time zone,
    actual_ship_date date,
    shipped_qty integer,
    source_system character varying(50)
);


--
-- Name: shift_summaries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shift_summaries (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    shift_date date NOT NULL,
    shift_type character varying(20) NOT NULL,
    station_id character varying(50),
    work_order_id character varying(36),
    product_id character varying(50),
    total_output integer DEFAULT 0,
    good_qty integer DEFAULT 0,
    defect_qty integer DEFAULT 0,
    scrap_qty integer DEFAULT 0,
    yield_rate double precision DEFAULT 0,
    target_output integer DEFAULT 0,
    achievement_rate double precision DEFAULT 0,
    report_count integer DEFAULT 0,
    total_cycle_time double precision DEFAULT 0,
    operator_count integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    created_by character varying(50),
    updated_by character varying(50)
);


--
-- Name: shipment_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shipment_items (
    id character varying(36) NOT NULL,
    shipment_id character varying(36) NOT NULL,
    product_id character varying(50) NOT NULL,
    product_name character varying(100),
    quantity integer NOT NULL,
    order_id character varying(50),
    packed_qty integer DEFAULT 0
);


--
-- Name: shipments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shipments (
    id character varying(36) NOT NULL,
    shipment_code character varying(50) NOT NULL,
    factory_id character varying(50) NOT NULL,
    customer_name character varying(100),
    container_count integer DEFAULT 1,
    plan_date date,
    etd date,
    status character varying(20) DEFAULT 'planned'::character varying,
    total_qty integer DEFAULT 0,
    total_amount numeric(14,2) DEFAULT 0,
    remark text,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: sim_erp_audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sim_erp_audit_logs (
    id character varying(36) NOT NULL,
    simulation_id character varying(36) NOT NULL,
    worker_ref character varying(50) NOT NULL,
    shift_id character varying(50) NOT NULL,
    task_type character varying(100) NOT NULL,
    zone_id character varying(50) NOT NULL,
    final_status character varying(20) NOT NULL,
    legal_blocked boolean DEFAULT false NOT NULL,
    total_cost_delta numeric(12,2) DEFAULT 0,
    max_required_break_minutes integer DEFAULT 0,
    total_penalty_score integer DEFAULT 0,
    simulation_input_hash character varying(64) NOT NULL,
    physics_core_version character varying(20) NOT NULL,
    plugin_manifest_hash character varying(256) NOT NULL,
    legislation_pack_hash character varying(256) NOT NULL,
    arbiter_version character varying(20) NOT NULL,
    optimizer_version character varying(50) DEFAULT 'manual'::character varying,
    snapshot_payload jsonb NOT NULL,
    plugin_records_payload jsonb NOT NULL,
    arbiter_result_payload jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: simulation_scorecards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.simulation_scorecards (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    engine_date date NOT NULL,
    models_simulated integer DEFAULT 0 NOT NULL,
    portfolio_score numeric(6,2) NOT NULL,
    weights jsonb,
    top_constraint character varying(200),
    lever_deltas jsonb,
    detail jsonb,
    source character varying(40) DEFAULT 'portfolio_sim'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE simulation_scorecards; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.simulation_scorecards IS '机种组合推演的记分卡历史：分数、权重、瓶颈、杠杆对比。推演读数，不是现场事实。';


--
-- Name: skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skills (
    id integer NOT NULL,
    code character varying(20) NOT NULL,
    name character varying(100) NOT NULL,
    category character varying(50),
    description text,
    is_active boolean,
    skill_code character varying(50),
    skill_name character varying(100)
);


--
-- Name: skills_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.skills_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: skills_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.skills_id_seq OWNED BY public.skills.id;


--
-- Name: spc_chart_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.spc_chart_config (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    characteristic_code character varying(50) NOT NULL,
    characteristic_name character varying(100),
    chart_type character varying(20) DEFAULT 'Xbar-R'::character varying,
    ucl double precision,
    cl double precision,
    lcl double precision,
    usl double precision,
    lsl double precision,
    target double precision,
    subgroup_size integer DEFAULT 5,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: spc_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.spc_configs (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_id character varying(50),
    station_id character varying(50),
    characteristic_code character varying(50) NOT NULL,
    sample_size integer,
    sample_interval integer NOT NULL,
    control_rule character varying(50),
    is_active boolean,
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: standard_operation_times; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.standard_operation_times (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_id character varying(50) NOT NULL,
    routing_step character varying(50),
    operation_seq integer,
    operation_name character varying(100) NOT NULL,
    station_id character varying(50),
    work_center character varying(50),
    standard_time_min double precision,
    unit_time_type character varying(20),
    setup_time_min double precision,
    setup_before_start_time_min double precision,
    post_operation_time_min double precision,
    batch_size integer,
    rating_factor double precision,
    allowance_rate double precision,
    effective_standard_time double precision,
    version character varying(20),
    is_active boolean,
    validity_start timestamp without time zone,
    validity_end timestamp without time zone,
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: station_capacity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.station_capacity (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    station_id character varying(50) NOT NULL,
    available_hours_per_day double precision DEFAULT 16,
    efficiency_rate double precision DEFAULT 0.85,
    setup_time_minutes double precision DEFAULT 30,
    max_concurrent_orders integer DEFAULT 1,
    maintenance_day character varying(10),
    required_skills text,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    source character varying(40) DEFAULT 'manual'::character varying NOT NULL,
    source_note text,
    verified_at timestamp without time zone
);


--
-- Name: stations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stations (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    workshop_id character varying(50),
    station_code character varying(50) NOT NULL,
    station_name character varying(100) NOT NULL,
    station_type character varying(50) NOT NULL,
    capacity integer NOT NULL,
    capacity_unit character varying(20) NOT NULL,
    equipment_count integer NOT NULL,
    status character varying(20) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    created_by character varying(50),
    capacity_per_hour integer DEFAULT 0,
    equipment_ids jsonb DEFAULT '[]'::jsonb
);


--
-- Name: stock_alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stock_alerts (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    alert_type character varying(30) NOT NULL,
    material_id character varying(50) NOT NULL,
    material_code character varying(50),
    material_name character varying(100),
    warehouse_id character varying(36),
    current_qty integer,
    threshold_qty integer,
    days_inactive integer,
    severity character varying(20) DEFAULT 'warning'::character varying,
    status character varying(20) DEFAULT 'open'::character varying,
    resolved_by character varying(50),
    resolved_at timestamp without time zone,
    remark text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: supplier_evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supplier_evaluations (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    supplier_id character varying(50) NOT NULL,
    supplier_name character varying(200),
    period character varying(20) DEFAULT '2026-08'::character varying,
    score_price numeric(5,2) DEFAULT 0,
    score_delivery numeric(5,2) DEFAULT 0,
    score_quality numeric(5,2) DEFAULT 0,
    total_score numeric(5,2) DEFAULT 0,
    grade character varying(2) DEFAULT 'C'::character varying,
    order_count integer DEFAULT 0,
    on_time_count integer DEFAULT 0,
    otif_rate numeric(5,2) DEFAULT 0,
    remark character varying(500),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: supplier_materials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supplier_materials (
    id character varying(36) DEFAULT gen_random_uuid() NOT NULL,
    supplier_id character varying(36) NOT NULL,
    material_code character varying(50) NOT NULL,
    is_active boolean DEFAULT true,
    is_primary boolean DEFAULT false,
    unit_cost numeric(15,2) NOT NULL,
    min_order_qty integer DEFAULT 1,
    lead_time_days integer DEFAULT 7,
    quality_rating double precision DEFAULT 5.0,
    description character varying(200),
    created_by character varying(50),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: supplier_prices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supplier_prices (
    id character varying(36) NOT NULL,
    supplier_id character varying(36) NOT NULL,
    material_code character varying(50) NOT NULL,
    material_name character varying(200),
    unit_price numeric(12,4) NOT NULL,
    currency character varying(10) DEFAULT 'CNY'::character varying,
    moq integer DEFAULT 1,
    lead_days integer DEFAULT 7,
    valid_from date,
    valid_to date,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: supplier_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supplier_profiles (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    supplier_code character varying(50) NOT NULL,
    supplier_name character varying(200) NOT NULL,
    category character varying(50),
    contact_person character varying(100),
    contact_phone character varying(50),
    payment_terms character varying(100) DEFAULT '月结30天'::character varying,
    credit_days integer DEFAULT 30,
    status character varying(20) DEFAULT 'active'::character varying,
    qualification character varying(100),
    remark character varying(500),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: suppliers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.suppliers (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    supplier_code character varying(50) NOT NULL,
    supplier_name character varying(200) NOT NULL,
    contact_person character varying(100),
    phone character varying(50),
    email character varying(200),
    category character varying(50),
    rating numeric(3,2) DEFAULT 3.0,
    on_time_rate numeric(5,2) DEFAULT 0,
    quality_rate numeric(5,2) DEFAULT 0,
    avg_lead_days integer DEFAULT 7,
    is_approved boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    address text,
    is_active boolean DEFAULT true,
    lead_time_days integer DEFAULT 7,
    moq_min integer DEFAULT 1,
    eoq_suggested numeric(15,2),
    preferred_for character varying(200)
);


--
-- Name: teams; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.teams (
    id character varying(36) NOT NULL,
    dept_id character varying(36) NOT NULL,
    team_code character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    leader_id character varying(50),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: time_study_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.time_study_records (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    product_id character varying(50) NOT NULL,
    station_id character varying(50) NOT NULL,
    operation_name character varying(100) NOT NULL,
    operator_id character varying(50),
    observer_id character varying(50),
    observation_date timestamp without time zone NOT NULL,
    observed_cycles json,
    cycle_count integer,
    average_time double precision,
    rating_factor double precision,
    normal_time double precision,
    allowed_time double precision,
    allowance_rate double precision,
    method character varying(50),
    status character varying(20),
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: tms_agent_actions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tms_agent_actions (
    id character varying(36) NOT NULL,
    agent_id character varying(100) NOT NULL,
    action_type character varying(50) NOT NULL,
    target_task_id character varying(36),
    payload jsonb,
    result jsonb,
    status character varying(20),
    requires_confirmation boolean,
    idempotency_key character varying(100),
    created_at timestamp without time zone NOT NULL
);


--
-- Name: tms_agent_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tms_agent_registry (
    agent_id character varying(100) NOT NULL,
    permission_level integer DEFAULT 1 NOT NULL,
    whitelisted boolean DEFAULT false NOT NULL,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: tms_approval_flows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tms_approval_flows (
    id character varying(36) NOT NULL,
    flow_code character varying(50) NOT NULL,
    task_id character varying(36) NOT NULL,
    flow_type character varying(50) NOT NULL,
    steps jsonb NOT NULL,
    current_step integer,
    status character varying(30),
    initiated_by character varying(50),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: tms_approval_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tms_approval_records (
    id character varying(36) NOT NULL,
    flow_id character varying(36) NOT NULL,
    step_index integer NOT NULL,
    approver_id character varying(36),
    action character varying(20) NOT NULL,
    comment text,
    acted_by character varying(100) NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: tms_distribution_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tms_distribution_logs (
    id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    strategy character varying(50) NOT NULL,
    candidate_scores jsonb,
    selected_user_id character varying(36),
    reason text,
    triggered_by character varying(100) NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: tms_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tms_tasks (
    id character varying(36) NOT NULL,
    task_code character varying(50) NOT NULL,
    title character varying(200) NOT NULL,
    description text,
    task_type character varying(50) NOT NULL,
    source character varying(50),
    priority character varying(20),
    points integer,
    status character varying(30),
    distribution_strategy character varying(50),
    assigned_to character varying(36),
    assigned_by character varying(100),
    candidate_pool jsonb,
    required_skills jsonb,
    required_roles jsonb,
    deadline timestamp without time zone,
    approval_flow_id character varying(36),
    agent_context jsonb,
    metadata jsonb,
    related_work_order_id character varying(36),
    created_by character varying(50),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: tms_webhook_subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tms_webhook_subscriptions (
    id character varying(36) NOT NULL,
    agent_id character varying(100) NOT NULL,
    event_types jsonb NOT NULL,
    webhook_url character varying(500) NOT NULL,
    secret character varying(100),
    is_active boolean,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: trainer_defects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trainer_defects (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NOT NULL,
    user_id character varying(64) NOT NULL,
    factory_id character varying(64),
    source character varying(32) DEFAULT 'user_report'::character varying NOT NULL,
    category character varying(64) NOT NULL,
    severity character varying(16) DEFAULT 'medium'::character varying NOT NULL,
    title character varying(255) NOT NULL,
    expected text,
    actual text,
    reproduction jsonb DEFAULT '[]'::jsonb NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(32) DEFAULT 'open'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: training_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_records (
    id integer NOT NULL,
    user_id character varying(36) NOT NULL,
    skill_id integer NOT NULL,
    training_type character varying(50),
    trainer character varying(100),
    start_date timestamp without time zone NOT NULL,
    end_date timestamp without time zone,
    hours numeric(5,2),
    result character varying(20),
    certificate_no character varying(50),
    created_at timestamp without time zone NOT NULL,
    notes text
);


--
-- Name: training_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_records_id_seq OWNED BY public.training_records.id;


--
-- Name: training_scenarios; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_scenarios (
    id integer NOT NULL,
    scenario_code character varying(64) NOT NULL,
    title character varying(255) NOT NULL,
    position_code character varying(64) NOT NULL,
    industry_code character varying(64) DEFAULT 'generic'::character varying NOT NULL,
    difficulty integer DEFAULT 1 NOT NULL,
    description text,
    script jsonb NOT NULL,
    evaluation_rubric jsonb,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: training_scenarios_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_scenarios_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_scenarios_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_scenarios_id_seq OWNED BY public.training_scenarios.id;


--
-- Name: training_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scenario_id integer NOT NULL,
    user_id character varying(64) NOT NULL,
    factory_id character varying(64),
    sandbox boolean DEFAULT true NOT NULL,
    status character varying(32) DEFAULT 'in_progress'::character varying NOT NULL,
    score numeric(5,2),
    evaluation jsonb,
    transcript jsonb,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    mode character varying(32) DEFAULT 'role_practice'::character varying NOT NULL,
    learner_role_code character varying(64)
);


--
-- Name: user_invitations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_invitations (
    id uuid NOT NULL,
    email character varying(100) NOT NULL,
    factory_id character varying(50) NOT NULL,
    role character varying(20) NOT NULL,
    token character varying(64) NOT NULL,
    accepted boolean NOT NULL,
    invited_by character varying(50),
    expires_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: user_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_roles (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    role_id character varying(36) NOT NULL,
    is_primary boolean,
    assigned_by character varying(50),
    assigned_at timestamp without time zone NOT NULL,
    expires_at timestamp without time zone
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id character varying(36) NOT NULL,
    username character varying(50) NOT NULL,
    email character varying(100) NOT NULL,
    hashed_password character varying(255) NOT NULL,
    full_name character varying(100),
    factory_id character varying(50),
    role character varying(20),
    is_active boolean,
    is_superuser boolean,
    last_login timestamp without time zone,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    role_id character varying(36),
    work_center character varying(20),
    active_factory_id character varying(50),
    password_reset_token character varying(255),
    password_reset_expires timestamp without time zone
);


--
-- Name: vf_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vf_config (
    factory_id character varying(50) NOT NULL,
    key character varying(50) NOT NULL,
    value character varying(100),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: vf_daily_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vf_daily_snapshots (
    id integer NOT NULL,
    factory_id character varying(50) NOT NULL,
    snapshot_date date NOT NULL,
    day integer NOT NULL,
    score numeric(6,1),
    revenue numeric(14,0),
    delivery_rate numeric(6,1),
    produced_qty integer,
    orders_qty integer,
    orders_amount numeric(14,0),
    wip_orders integer,
    risk_level character varying(10),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: vf_daily_snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vf_daily_snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vf_daily_snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vf_daily_snapshots_id_seq OWNED BY public.vf_daily_snapshots.id;


--
-- Name: vf_emails; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vf_emails (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    thread_key character varying(180) NOT NULL,
    sender_role character varying(80) NOT NULL,
    recipient_role character varying(80) NOT NULL,
    recipient_address character varying(160) NOT NULL,
    subject character varying(240) NOT NULL,
    body text NOT NULL,
    status character varying(30) DEFAULT 'simulated'::character varying NOT NULL,
    related_type character varying(80),
    related_id character varying(120),
    sent_at timestamp without time zone DEFAULT now() NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: vf_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vf_events (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    event_key character varying(240) NOT NULL,
    event_type character varying(80) NOT NULL,
    title character varying(240) NOT NULL,
    severity character varying(20) DEFAULT 'info'::character varying NOT NULL,
    source_type character varying(80),
    source_id character varying(120),
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp without time zone DEFAULT now() NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: vf_quality_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vf_quality_profiles (
    profile_code character varying(80) NOT NULL,
    factory_id character varying(50),
    industry_code character varying(80) NOT NULL,
    country_code character varying(8) NOT NULL,
    maturity_level character varying(80) NOT NULL,
    base_defect_rate numeric(8,6) NOT NULL,
    concentration numeric(8,2) DEFAULT 80 NOT NULL,
    special_cause_rate numeric(8,6) DEFAULT 0.04 NOT NULL,
    special_cause_multiplier numeric(8,3) DEFAULT 2.5 NOT NULL,
    scrap_rate numeric(8,6) DEFAULT 0.002 NOT NULL,
    review_threshold numeric(8,6) NOT NULL,
    source_label character varying(200) NOT NULL,
    source_notes text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: warehouses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.warehouses (
    id character varying(36) NOT NULL,
    warehouse_code character varying(50) NOT NULL,
    warehouse_name character varying(100) NOT NULL,
    factory_id character varying(50) NOT NULL,
    warehouse_type character varying(20) NOT NULL,
    address character varying(255),
    status character varying(20),
    created_by character varying(50),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    total_volume_m3 numeric(14,2),
    usable_volume_m3 numeric(14,2),
    manager_id character varying(50)
);


--
-- Name: wms_automation_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wms_automation_jobs (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    job_code character varying(50) NOT NULL,
    job_type character varying(30) NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb,
    status character varying(20) DEFAULT 'queued'::character varying,
    priority integer DEFAULT 5,
    source_location character varying(100),
    target_location character varying(100),
    material_code character varying(50),
    quantity integer,
    error_message text,
    dispatched_at timestamp without time zone,
    completed_at timestamp without time zone,
    created_by character varying(50),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: wms_barcodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wms_barcodes (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    material_id character varying(50) NOT NULL,
    material_code character varying(50) NOT NULL,
    barcode character varying(100) NOT NULL,
    barcode_type character varying(20) DEFAULT 'CODE128'::character varying,
    batch_code character varying(50),
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: wms_inventory_pool_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wms_inventory_pool_members (
    id character varying(36) NOT NULL,
    pool_id character varying(36) NOT NULL,
    warehouse_id character varying(36) NOT NULL,
    allocated_qty integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: wms_inventory_pools; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wms_inventory_pools (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    pool_code character varying(50) NOT NULL,
    pool_name character varying(100) NOT NULL,
    material_id character varying(50) NOT NULL,
    material_code character varying(50),
    shared_qty integer DEFAULT 0,
    status character varying(20) DEFAULT 'active'::character varying,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: wms_rfid_count_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wms_rfid_count_items (
    id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    tag_id character varying(100) NOT NULL,
    material_code character varying(50),
    expected_qty integer DEFAULT 1,
    scanned_qty integer DEFAULT 0,
    variance_qty integer DEFAULT 0,
    status character varying(20) DEFAULT 'pending'::character varying,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: wms_rfid_count_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wms_rfid_count_sessions (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    warehouse_id character varying(36),
    session_code character varying(50) NOT NULL,
    status character varying(20) DEFAULT 'open'::character varying,
    total_tags integer DEFAULT 0,
    matched_tags integer DEFAULT 0,
    variance_tags integer DEFAULT 0,
    created_by character varying(50),
    completed_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: wms_rfid_tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wms_rfid_tags (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    tag_id character varying(100) NOT NULL,
    material_id character varying(50),
    material_code character varying(50),
    inventory_id character varying(36),
    batch_code character varying(50),
    status character varying(20) DEFAULT 'active'::character varying,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: wms_transfer_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wms_transfer_requests (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    request_code character varying(50) NOT NULL,
    material_id character varying(50) NOT NULL,
    material_code character varying(50),
    material_name character varying(100),
    quantity integer NOT NULL,
    from_warehouse_id character varying(36) NOT NULL,
    to_warehouse_id character varying(36) NOT NULL,
    to_location_id character varying(36),
    status character varying(20) DEFAULT 'draft'::character varying,
    requested_by character varying(50),
    approved_by character varying(50),
    approved_at timestamp without time zone,
    rejected_reason character varying(500),
    completed_at timestamp without time zone,
    remark text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: wo_status_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wo_status_logs (
    id character varying(36) NOT NULL,
    work_order_id character varying(36) NOT NULL,
    action character varying(30) NOT NULL,
    from_status character varying(20),
    to_status character varying(20) NOT NULL,
    operator character varying(50) NOT NULL,
    operator_role character varying(50),
    comment character varying(500),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: work_cell_layouts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.work_cell_layouts (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    work_cell_id character varying(50) NOT NULL,
    product_family_id character varying(50),
    layout_diagram_url character varying(255),
    material_flow_path json,
    operator_movement_path json,
    takt_time_alignment character varying(50),
    storage_location_type character varying(50),
    description text,
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_by character varying(50),
    updated_at timestamp without time zone
);


--
-- Name: work_order_materials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.work_order_materials (
    id character varying(36) NOT NULL,
    work_order_id character varying(36) NOT NULL,
    material_id character varying(50),
    material_code character varying(50),
    material_name character varying(256),
    qty_per_unit numeric(18,4),
    required_qty numeric(18,4) DEFAULT 0 NOT NULL,
    unit character varying(20),
    received_qty numeric(18,4) DEFAULT 0,
    available_qty numeric(18,4) DEFAULT 0,
    shortage_qty numeric(18,4) DEFAULT 0,
    remark text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    level integer,
    parent_code character varying(100),
    allocated_qty numeric(18,4) DEFAULT 0 NOT NULL,
    item_type character varying(10)
);


--
-- Name: work_order_pause_reasons; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.work_order_pause_reasons (
    id character varying(36) DEFAULT gen_random_uuid() NOT NULL,
    factory_id character varying(50) NOT NULL,
    code character varying(20) NOT NULL,
    description character varying(100) NOT NULL,
    category character varying(20) NOT NULL,
    is_active boolean DEFAULT true,
    sort_order integer DEFAULT 0,
    created_by character varying(50),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: work_order_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.work_order_templates (
    id character varying(36) NOT NULL,
    factory_id character varying(50),
    template_code character varying(50) NOT NULL,
    template_name character varying(100) NOT NULL,
    wo_type character varying(20) DEFAULT 'master'::character varying,
    description text,
    default_priority integer DEFAULT 3,
    default_routing_template_id character varying(36),
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    module character varying(30) DEFAULT 'production'::character varying,
    form_fields jsonb DEFAULT '[]'::jsonb,
    standard_ref character varying(200),
    badge_text character varying(100),
    color character varying(20) DEFAULT '#1677ff'::character varying,
    sort_order integer DEFAULT 0
);


--
-- Name: COLUMN work_order_templates.module; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.work_order_templates.module IS '所属模块: qms/equipment/wms/production/pp';


--
-- Name: COLUMN work_order_templates.form_fields; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.work_order_templates.form_fields IS '动态表单字段定义 JSON [{key,label,type,required?,options?,placeholder?,suffix?,span?}]';


--
-- Name: COLUMN work_order_templates.standard_ref; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.work_order_templates.standard_ref IS '参考标准（如 ISO 9001 / IATF 16949）';


--
-- Name: COLUMN work_order_templates.badge_text; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.work_order_templates.badge_text IS '卡片角标文字';


--
-- Name: COLUMN work_order_templates.color; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.work_order_templates.color IS '模板主题色';


--
-- Name: work_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.work_orders (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    work_order_code character varying(50) NOT NULL,
    sales_order_id character varying(50),
    plan_id character varying(50),
    product_id character varying(50) NOT NULL,
    routing_id character varying(50),
    bom_version character varying(20),
    planned_qty integer NOT NULL,
    unit character varying(20) NOT NULL,
    completed_qty integer NOT NULL,
    good_qty integer NOT NULL,
    defect_qty integer NOT NULL,
    scrap_qty integer NOT NULL,
    status character varying(20) NOT NULL,
    priority character varying(20) NOT NULL,
    planned_start timestamp without time zone,
    planned_due timestamp without time zone,
    actual_start timestamp without time zone,
    actual_complete timestamp without time zone,
    assigned_station_id character varying(36),
    current_routing_step integer NOT NULL,
    remark character varying(500),
    created_by character varying(50) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    updated_by character varying(32),
    parent_work_order_id character varying(36),
    wo_type character varying(20) DEFAULT 'master'::character varying NOT NULL,
    process_code character varying(20),
    operation_seq integer,
    released_by character varying(50),
    completed_by character varying(50),
    assigned_to character varying(36),
    work_center character varying(20),
    routing_template_id character varying(36),
    material_status character varying(20) DEFAULT 'unknown'::character varying,
    current_stage character varying(30),
    next_station character varying(50),
    in_progress_status character varying(30),
    partial_completion_percentage numeric(5,2) DEFAULT 0,
    reserved_warehouse character varying(50),
    reserved_qty integer DEFAULT 0,
    reserved_at timestamp without time zone,
    release_action_id character varying(36),
    pause_reason_id character varying(36),
    pause_start_time timestamp without time zone,
    pause_end_time timestamp without time zone,
    source_plan_id character varying(36)
);


--
-- Name: COLUMN work_orders.reserved_warehouse; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.work_orders.reserved_warehouse IS 'Warehouse code where inventory was reserved for this work order';


--
-- Name: COLUMN work_orders.reserved_qty; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.work_orders.reserved_qty IS 'Quantity of inventory reserved from warehouse';


--
-- Name: COLUMN work_orders.reserved_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.work_orders.reserved_at IS 'Timestamp when inventory reservation was made';


--
-- Name: COLUMN work_orders.release_action_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.work_orders.release_action_id IS 'External reservation action ID from WMS system';


--
-- Name: work_teams; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.work_teams (
    id character varying(36) NOT NULL,
    factory_id character varying(50) NOT NULL,
    team_code character varying(50) NOT NULL,
    team_name character varying(100) NOT NULL,
    leader_id character varying(50),
    member_ids jsonb,
    description text,
    is_active boolean,
    created_by character varying(50),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: workflow_action_gates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_action_gates (
    id character varying(36) DEFAULT gen_random_uuid() NOT NULL,
    factory_id character varying(50) NOT NULL,
    action character varying(20) NOT NULL,
    required_role character varying(20) NOT NULL,
    description character varying(200),
    is_active boolean DEFAULT true,
    sort_order integer DEFAULT 0,
    created_by character varying(50),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: workflow_rule_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_rule_versions (
    id character varying(36) DEFAULT gen_random_uuid() NOT NULL,
    factory_id character varying(50) NOT NULL,
    version_number integer NOT NULL,
    description character varying(500),
    effective_from timestamp with time zone NOT NULL,
    expires_at timestamp with time zone,
    is_active boolean DEFAULT true,
    created_by character varying(50),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: workflow_state_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_state_rules (
    id character varying(36) DEFAULT gen_random_uuid() NOT NULL,
    factory_id character varying(50) NOT NULL,
    current_state character varying(20) NOT NULL,
    allowed_next_state character varying(20) NOT NULL,
    description character varying(200),
    is_active boolean DEFAULT true,
    sort_order integer DEFAULT 0,
    created_by character varying(50),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: commander_cycles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commander_cycles ALTER COLUMN id SET DEFAULT nextval('public.commander_cycles_id_seq'::regclass);


--
-- Name: employee_skills id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_skills ALTER COLUMN id SET DEFAULT nextval('public.employee_skills_id_seq'::regclass);


--
-- Name: enghub_bom_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enghub_bom_items ALTER COLUMN id SET DEFAULT nextval('public.enghub_bom_items_id_seq'::regclass);


--
-- Name: enghub_bom_sync_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enghub_bom_sync_log ALTER COLUMN id SET DEFAULT nextval('public.enghub_bom_sync_log_id_seq'::regclass);


--
-- Name: enterprise_knowledge_documents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_knowledge_documents ALTER COLUMN id SET DEFAULT nextval('public.enterprise_knowledge_documents_id_seq'::regclass);


--
-- Name: industry_knowledge id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.industry_knowledge ALTER COLUMN id SET DEFAULT nextval('public.industry_knowledge_id_seq'::regclass);


--
-- Name: login_attempts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_attempts ALTER COLUMN id SET DEFAULT nextval('public.login_attempts_id_seq'::regclass);


--
-- Name: position_sops id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_sops ALTER COLUMN id SET DEFAULT nextval('public.position_sops_id_seq'::regclass);


--
-- Name: skills id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills ALTER COLUMN id SET DEFAULT nextval('public.skills_id_seq'::regclass);


--
-- Name: training_records id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_records ALTER COLUMN id SET DEFAULT nextval('public.training_records_id_seq'::regclass);


--
-- Name: training_scenarios id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_scenarios ALTER COLUMN id SET DEFAULT nextval('public.training_scenarios_id_seq'::regclass);


--
-- Name: vf_daily_snapshots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vf_daily_snapshots ALTER COLUMN id SET DEFAULT nextval('public.vf_daily_snapshots_id_seq'::regclass);


--
-- Name: action_studies action_studies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_studies
    ADD CONSTRAINT action_studies_pkey PRIMARY KEY (id);


--
-- Name: agent_checkpoints agent_checkpoints_checkpoint_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_checkpoints
    ADD CONSTRAINT agent_checkpoints_checkpoint_key_key UNIQUE (checkpoint_key);


--
-- Name: agent_checkpoints agent_checkpoints_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_checkpoints
    ADD CONSTRAINT agent_checkpoints_pkey PRIMARY KEY (id);


--
-- Name: agent_events agent_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_events
    ADD CONSTRAINT agent_events_pkey PRIMARY KEY (id);


--
-- Name: agent_heartbeats agent_heartbeats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_heartbeats
    ADD CONSTRAINT agent_heartbeats_pkey PRIMARY KEY (id);


--
-- Name: agent_tasks agent_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tasks
    ADD CONSTRAINT agent_tasks_pkey PRIMARY KEY (id);


--
-- Name: agent_work_log agent_work_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_work_log
    ADD CONSTRAINT agent_work_log_pkey PRIMARY KEY (id);


--
-- Name: ai_action_approvals ai_action_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_action_approvals
    ADD CONSTRAINT ai_action_approvals_pkey PRIMARY KEY (id);


--
-- Name: ai_memories ai_memories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_memories
    ADD CONSTRAINT ai_memories_pkey PRIMARY KEY (id);


--
-- Name: ai_memory_candidates ai_memory_candidates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_memory_candidates
    ADD CONSTRAINT ai_memory_candidates_pkey PRIMARY KEY (id);


--
-- Name: alert_intelligence_reviews alert_intelligence_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alert_intelligence_reviews
    ADD CONSTRAINT alert_intelligence_reviews_pkey PRIMARY KEY (id);


--
-- Name: andon_categories andon_categories_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.andon_categories
    ADD CONSTRAINT andon_categories_code_key UNIQUE (code);


--
-- Name: andon_categories andon_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.andon_categories
    ADD CONSTRAINT andon_categories_pkey PRIMARY KEY (id);


--
-- Name: andon_escalation_logs andon_escalation_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.andon_escalation_logs
    ADD CONSTRAINT andon_escalation_logs_pkey PRIMARY KEY (id);


--
-- Name: andon_tickets andon_tickets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.andon_tickets
    ADD CONSTRAINT andon_tickets_pkey PRIMARY KEY (id);


--
-- Name: andon_tickets andon_tickets_ticket_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.andon_tickets
    ADD CONSTRAINT andon_tickets_ticket_code_key UNIQUE (ticket_code);


--
-- Name: aps_coordination_meetings aps_coordination_meetings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aps_coordination_meetings
    ADD CONSTRAINT aps_coordination_meetings_pkey PRIMARY KEY (id);


--
-- Name: aps_dlq_requests aps_dlq_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aps_dlq_requests
    ADD CONSTRAINT aps_dlq_requests_pkey PRIMARY KEY (id);


--
-- Name: aps_holidays aps_holidays_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aps_holidays
    ADD CONSTRAINT aps_holidays_pkey PRIMARY KEY (id);


--
-- Name: aps_plan_events aps_plan_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aps_plan_events
    ADD CONSTRAINT aps_plan_events_pkey PRIMARY KEY (id);


--
-- Name: aps_planner_activities aps_planner_activities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aps_planner_activities
    ADD CONSTRAINT aps_planner_activities_pkey PRIMARY KEY (id);


--
-- Name: aps_schedule_requests aps_schedule_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aps_schedule_requests
    ADD CONSTRAINT aps_schedule_requests_pkey PRIMARY KEY (id);


--
-- Name: aps_schedule_tasks aps_schedule_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aps_schedule_tasks
    ADD CONSTRAINT aps_schedule_tasks_pkey PRIMARY KEY (id);


--
-- Name: aps_schedules aps_schedules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aps_schedules
    ADD CONSTRAINT aps_schedules_pkey PRIMARY KEY (id);


--
-- Name: aps_schedules aps_schedules_schedule_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aps_schedules
    ADD CONSTRAINT aps_schedules_schedule_code_key UNIQUE (schedule_code);


--
-- Name: aps_work_calendars aps_work_calendars_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aps_work_calendars
    ADD CONSTRAINT aps_work_calendars_pkey PRIMARY KEY (id);


--
-- Name: archive_records archive_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.archive_records
    ADD CONSTRAINT archive_records_pkey PRIMARY KEY (id);


--
-- Name: arrival_plans arrival_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.arrival_plans
    ADD CONSTRAINT arrival_plans_pkey PRIMARY KEY (id);


--
-- Name: attendance attendance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attendance
    ADD CONSTRAINT attendance_pkey PRIMARY KEY (id);


--
-- Name: automation_config automation_config_factory_id_workflow_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_config
    ADD CONSTRAINT automation_config_factory_id_workflow_key_key UNIQUE (factory_id, workflow_key);


--
-- Name: automation_config automation_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_config
    ADD CONSTRAINT automation_config_pkey PRIMARY KEY (id);


--
-- Name: bom_items bom_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bom_items
    ADD CONSTRAINT bom_items_pkey PRIMARY KEY (id);


--
-- Name: capa_cases capa_cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capa_cases
    ADD CONSTRAINT capa_cases_pkey PRIMARY KEY (id);


--
-- Name: capa_fishbone_items capa_fishbone_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capa_fishbone_items
    ADD CONSTRAINT capa_fishbone_items_pkey PRIMARY KEY (id);


--
-- Name: capa_why_steps capa_why_steps_case_id_step_num_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capa_why_steps
    ADD CONSTRAINT capa_why_steps_case_id_step_num_key UNIQUE (case_id, step_num);


--
-- Name: capa_why_steps capa_why_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capa_why_steps
    ADD CONSTRAINT capa_why_steps_pkey PRIMARY KEY (id);


--
-- Name: chat_eval_cases chat_eval_cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_eval_cases
    ADD CONSTRAINT chat_eval_cases_pkey PRIMARY KEY (id);


--
-- Name: chat_events chat_events_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_events
    ADD CONSTRAINT chat_events_event_id_key UNIQUE (event_id);


--
-- Name: chat_events chat_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_events
    ADD CONSTRAINT chat_events_pkey PRIMARY KEY (id);


--
-- Name: chat_goal_metrics chat_goal_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_goal_metrics
    ADD CONSTRAINT chat_goal_metrics_pkey PRIMARY KEY (id);


--
-- Name: chat_goals chat_goals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_goals
    ADD CONSTRAINT chat_goals_pkey PRIMARY KEY (id);


--
-- Name: chat_goals chat_goals_session_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_goals
    ADD CONSTRAINT chat_goals_session_id_key UNIQUE (session_id);


--
-- Name: chat_memories chat_memories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_memories
    ADD CONSTRAINT chat_memories_pkey PRIMARY KEY (id);


--
-- Name: chat_message_attachments chat_message_attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_message_attachments
    ADD CONSTRAINT chat_message_attachments_pkey PRIMARY KEY (id);


--
-- Name: chat_messages chat_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_pkey PRIMARY KEY (id);


--
-- Name: chat_quick_commands chat_quick_commands_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_quick_commands
    ADD CONSTRAINT chat_quick_commands_pkey PRIMARY KEY (id);


--
-- Name: chat_session_events chat_session_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_session_events
    ADD CONSTRAINT chat_session_events_pkey PRIMARY KEY (id);


--
-- Name: chat_sessions chat_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_sessions
    ADD CONSTRAINT chat_sessions_pkey PRIMARY KEY (id);


--
-- Name: chat_telemetry chat_telemetry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_telemetry
    ADD CONSTRAINT chat_telemetry_pkey PRIMARY KEY (id);


--
-- Name: chatbot_ticket_approval_flow chatbot_ticket_approval_flow_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chatbot_ticket_approval_flow
    ADD CONSTRAINT chatbot_ticket_approval_flow_pkey PRIMARY KEY (id);


--
-- Name: chatbot_tickets chatbot_tickets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chatbot_tickets
    ADD CONSTRAINT chatbot_tickets_pkey PRIMARY KEY (id);


--
-- Name: chatbot_tickets chatbot_tickets_ticket_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chatbot_tickets
    ADD CONSTRAINT chatbot_tickets_ticket_code_key UNIQUE (ticket_code);


--
-- Name: code_tables code_tables_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.code_tables
    ADD CONSTRAINT code_tables_pkey PRIMARY KEY (id);


--
-- Name: commander_cycles commander_cycles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commander_cycles
    ADD CONSTRAINT commander_cycles_pkey PRIMARY KEY (id);


--
-- Name: commander_decision_log commander_decision_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commander_decision_log
    ADD CONSTRAINT commander_decision_log_pkey PRIMARY KEY (id);


--
-- Name: commander_plans commander_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commander_plans
    ADD CONSTRAINT commander_plans_pkey PRIMARY KEY (id);


--
-- Name: commander_sessions commander_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commander_sessions
    ADD CONSTRAINT commander_sessions_pkey PRIMARY KEY (user_id, factory_id);


--
-- Name: cost_parameters cost_parameters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_parameters
    ADD CONSTRAINT cost_parameters_pkey PRIMARY KEY (id);


--
-- Name: crew_decisions crew_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_decisions
    ADD CONSTRAINT crew_decisions_pkey PRIMARY KEY (id);


--
-- Name: cycle_count_items cycle_count_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycle_count_items
    ADD CONSTRAINT cycle_count_items_pkey PRIMARY KEY (id);


--
-- Name: cycle_count_tasks cycle_count_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycle_count_tasks
    ADD CONSTRAINT cycle_count_tasks_pkey PRIMARY KEY (id);


--
-- Name: cycle_count_tasks cycle_count_tasks_task_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycle_count_tasks
    ADD CONSTRAINT cycle_count_tasks_task_code_key UNIQUE (task_code);


--
-- Name: decision_records decision_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.decision_records
    ADD CONSTRAINT decision_records_pkey PRIMARY KEY (id);


--
-- Name: defect_daily_summary defect_daily_summary_factory_id_summary_date_defect_type_st_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.defect_daily_summary
    ADD CONSTRAINT defect_daily_summary_factory_id_summary_date_defect_type_st_key UNIQUE (factory_id, summary_date, defect_type, station_id);


--
-- Name: defect_daily_summary defect_daily_summary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.defect_daily_summary
    ADD CONSTRAINT defect_daily_summary_pkey PRIMARY KEY (id);


--
-- Name: defect_records defect_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.defect_records
    ADD CONSTRAINT defect_records_pkey PRIMARY KEY (id);


--
-- Name: defect_records defect_records_record_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.defect_records
    ADD CONSTRAINT defect_records_record_code_key UNIQUE (record_code);


--
-- Name: defects defects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.defects
    ADD CONSTRAINT defects_pkey PRIMARY KEY (id);


--
-- Name: departments departments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_pkey PRIMARY KEY (id);


--
-- Name: deterministic_logic_chains deterministic_logic_chains_chain_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deterministic_logic_chains
    ADD CONSTRAINT deterministic_logic_chains_chain_code_key UNIQUE (chain_code);


--
-- Name: deterministic_logic_chains deterministic_logic_chains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deterministic_logic_chains
    ADD CONSTRAINT deterministic_logic_chains_pkey PRIMARY KEY (id);


--
-- Name: employee_skills employee_skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_skills
    ADD CONSTRAINT employee_skills_pkey PRIMARY KEY (id);


--
-- Name: enghub_bom_items enghub_bom_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enghub_bom_items
    ADD CONSTRAINT enghub_bom_items_pkey PRIMARY KEY (id);


--
-- Name: enghub_bom_sync_log enghub_bom_sync_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enghub_bom_sync_log
    ADD CONSTRAINT enghub_bom_sync_log_pkey PRIMARY KEY (id);


--
-- Name: enghub_schema_migrations enghub_schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enghub_schema_migrations
    ADD CONSTRAINT enghub_schema_migrations_pkey PRIMARY KEY (migration_name);


--
-- Name: engine_loop_state engine_loop_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.engine_loop_state
    ADD CONSTRAINT engine_loop_state_pkey PRIMARY KEY (loop_name);


--
-- Name: engine_order_predictions engine_order_predictions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.engine_order_predictions
    ADD CONSTRAINT engine_order_predictions_pkey PRIMARY KEY (id);


--
-- Name: engineering_changes engineering_changes_ecn_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.engineering_changes
    ADD CONSTRAINT engineering_changes_ecn_code_key UNIQUE (ecn_code);


--
-- Name: engineering_changes engineering_changes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.engineering_changes
    ADD CONSTRAINT engineering_changes_pkey PRIMARY KEY (id);


--
-- Name: engineering_forms engineering_forms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.engineering_forms
    ADD CONSTRAINT engineering_forms_pkey PRIMARY KEY (id);


--
-- Name: enterprise_knowledge_documents enterprise_knowledge_documents_document_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_knowledge_documents
    ADD CONSTRAINT enterprise_knowledge_documents_document_code_key UNIQUE (document_code);


--
-- Name: enterprise_knowledge_documents enterprise_knowledge_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_knowledge_documents
    ADD CONSTRAINT enterprise_knowledge_documents_pkey PRIMARY KEY (id);


--
-- Name: equipment_downtime equipment_downtime_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equipment_downtime
    ADD CONSTRAINT equipment_downtime_pkey PRIMARY KEY (id);


--
-- Name: equipment equipment_equipment_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equipment
    ADD CONSTRAINT equipment_equipment_code_key UNIQUE (equipment_code);


--
-- Name: equipment equipment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equipment
    ADD CONSTRAINT equipment_pkey PRIMARY KEY (id);


--
-- Name: equipment_readings equipment_readings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equipment_readings
    ADD CONSTRAINT equipment_readings_pkey PRIMARY KEY (id);


--
-- Name: erp_inbound erp_inbound_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.erp_inbound
    ADD CONSTRAINT erp_inbound_pkey PRIMARY KEY (id);


--
-- Name: erp_outbound erp_outbound_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.erp_outbound
    ADD CONSTRAINT erp_outbound_pkey PRIMARY KEY (id);


--
-- Name: execution_events execution_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_events
    ADD CONSTRAINT execution_events_pkey PRIMARY KEY (id);


--
-- Name: factories factories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.factories
    ADD CONSTRAINT factories_pkey PRIMARY KEY (id);


--
-- Name: factory_rules factory_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.factory_rules
    ADD CONSTRAINT factory_rules_pkey PRIMARY KEY (id);


--
-- Name: files files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.files
    ADD CONSTRAINT files_pkey PRIMARY KEY (id);


--
-- Name: five_s_audits five_s_audits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.five_s_audits
    ADD CONSTRAINT five_s_audits_pkey PRIMARY KEY (id);


--
-- Name: followup_task_logs followup_task_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_task_logs
    ADD CONSTRAINT followup_task_logs_pkey PRIMARY KEY (id);


--
-- Name: followup_tasks followup_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_tasks
    ADD CONSTRAINT followup_tasks_pkey PRIMARY KEY (id);


--
-- Name: global_adjustable_params global_adjustable_params_param_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_adjustable_params
    ADD CONSTRAINT global_adjustable_params_param_code_key UNIQUE (param_code);


--
-- Name: global_adjustable_params global_adjustable_params_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_adjustable_params
    ADD CONSTRAINT global_adjustable_params_pkey PRIMARY KEY (id);


--
-- Name: goods_receipts goods_receipts_gr_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.goods_receipts
    ADD CONSTRAINT goods_receipts_gr_code_key UNIQUE (gr_code);


--
-- Name: goods_receipts goods_receipts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.goods_receipts
    ADD CONSTRAINT goods_receipts_pkey PRIMARY KEY (id);


--
-- Name: hourly_output_snapshots hourly_output_snapshots_factory_id_snapshot_date_snapshot_h_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hourly_output_snapshots
    ADD CONSTRAINT hourly_output_snapshots_factory_id_snapshot_date_snapshot_h_key UNIQUE (factory_id, snapshot_date, snapshot_hour, station_id);


--
-- Name: hourly_output_snapshots hourly_output_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hourly_output_snapshots
    ADD CONSTRAINT hourly_output_snapshots_pkey PRIMARY KEY (id);


--
-- Name: hr_employee_skills hr_employee_skills_hr_employee_id_skill_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hr_employee_skills
    ADD CONSTRAINT hr_employee_skills_hr_employee_id_skill_id_key UNIQUE (hr_employee_id, skill_id);


--
-- Name: hr_employee_skills hr_employee_skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hr_employee_skills
    ADD CONSTRAINT hr_employee_skills_pkey PRIMARY KEY (id);


--
-- Name: hr_employees hr_employees_factory_id_employee_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hr_employees
    ADD CONSTRAINT hr_employees_factory_id_employee_code_key UNIQUE (factory_id, employee_code);


--
-- Name: hr_employees hr_employees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hr_employees
    ADD CONSTRAINT hr_employees_pkey PRIMARY KEY (id);


--
-- Name: im_group_members im_group_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.im_group_members
    ADD CONSTRAINT im_group_members_pkey PRIMARY KEY (id);


--
-- Name: im_groups im_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.im_groups
    ADD CONSTRAINT im_groups_pkey PRIMARY KEY (id);


--
-- Name: im_messages im_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.im_messages
    ADD CONSTRAINT im_messages_pkey PRIMARY KEY (id);


--
-- Name: inbound_orders inbound_orders_inbound_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inbound_orders
    ADD CONSTRAINT inbound_orders_inbound_code_key UNIQUE (inbound_code);


--
-- Name: inbound_orders inbound_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inbound_orders
    ADD CONSTRAINT inbound_orders_pkey PRIMARY KEY (id);


--
-- Name: industry_knowledge industry_knowledge_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.industry_knowledge
    ADD CONSTRAINT industry_knowledge_pkey PRIMARY KEY (id);


--
-- Name: inspection_items inspection_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_items
    ADD CONSTRAINT inspection_items_pkey PRIMARY KEY (id);


--
-- Name: inspection_records inspection_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_records
    ADD CONSTRAINT inspection_records_pkey PRIMARY KEY (id);


--
-- Name: inspection_tasks inspection_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_tasks
    ADD CONSTRAINT inspection_tasks_pkey PRIMARY KEY (id);


--
-- Name: inspection_tasks inspection_tasks_task_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_tasks
    ADD CONSTRAINT inspection_tasks_task_code_key UNIQUE (task_code);


--
-- Name: inspections inspections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspections
    ADD CONSTRAINT inspections_pkey PRIMARY KEY (id);


--
-- Name: internal_meeting_attendees internal_meeting_attendees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.internal_meeting_attendees
    ADD CONSTRAINT internal_meeting_attendees_pkey PRIMARY KEY (id);


--
-- Name: internal_meetings internal_meetings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.internal_meetings
    ADD CONSTRAINT internal_meetings_pkey PRIMARY KEY (id);


--
-- Name: inventory_count_items inventory_count_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_count_items
    ADD CONSTRAINT inventory_count_items_pkey PRIMARY KEY (id);


--
-- Name: inventory_counts inventory_counts_count_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_counts
    ADD CONSTRAINT inventory_counts_count_code_key UNIQUE (count_code);


--
-- Name: inventory_counts inventory_counts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_counts
    ADD CONSTRAINT inventory_counts_pkey PRIMARY KEY (id);


--
-- Name: inventory_freezes inventory_freezes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_freezes
    ADD CONSTRAINT inventory_freezes_pkey PRIMARY KEY (id);


--
-- Name: inventory inventory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_pkey PRIMARY KEY (id);


--
-- Name: inventory_transactions inventory_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_transactions
    ADD CONSTRAINT inventory_transactions_pkey PRIMARY KEY (id);


--
-- Name: invoice_matching invoice_matching_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoice_matching
    ADD CONSTRAINT invoice_matching_pkey PRIMARY KEY (id);


--
-- Name: item_traceability item_traceability_item_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_traceability
    ADD CONSTRAINT item_traceability_item_code_key UNIQUE (item_code);


--
-- Name: item_traceability item_traceability_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_traceability
    ADD CONSTRAINT item_traceability_pkey PRIMARY KEY (id);


--
-- Name: job_card_time_logs job_card_time_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_card_time_logs
    ADD CONSTRAINT job_card_time_logs_pkey PRIMARY KEY (id);


--
-- Name: job_dispatches job_dispatches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_dispatches
    ADD CONSTRAINT job_dispatches_pkey PRIMARY KEY (id);


--
-- Name: kanban_systems kanban_systems_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kanban_systems
    ADD CONSTRAINT kanban_systems_pkey PRIMARY KEY (id);


--
-- Name: line_balance_analyses line_balance_analyses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.line_balance_analyses
    ADD CONSTRAINT line_balance_analyses_pkey PRIMARY KEY (id);


--
-- Name: line_profiles line_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.line_profiles
    ADD CONSTRAINT line_profiles_pkey PRIMARY KEY (id);


--
-- Name: locations locations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations
    ADD CONSTRAINT locations_pkey PRIMARY KEY (id);


--
-- Name: logic_chain_execution_log logic_chain_execution_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.logic_chain_execution_log
    ADD CONSTRAINT logic_chain_execution_log_pkey PRIMARY KEY (id);


--
-- Name: login_attempts login_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_attempts
    ADD CONSTRAINT login_attempts_pkey PRIMARY KEY (id);


--
-- Name: maintenance_checklist maintenance_checklist_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_checklist
    ADD CONSTRAINT maintenance_checklist_pkey PRIMARY KEY (id);


--
-- Name: maintenance_orders maintenance_orders_order_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_orders
    ADD CONSTRAINT maintenance_orders_order_code_key UNIQUE (order_code);


--
-- Name: maintenance_orders maintenance_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_orders
    ADD CONSTRAINT maintenance_orders_pkey PRIMARY KEY (id);


--
-- Name: maintenance_plans maintenance_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_plans
    ADD CONSTRAINT maintenance_plans_pkey PRIMARY KEY (id);


--
-- Name: maintenance_tasks maintenance_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_tasks
    ADD CONSTRAINT maintenance_tasks_pkey PRIMARY KEY (id);


--
-- Name: maintenance_tasks maintenance_tasks_task_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_tasks
    ADD CONSTRAINT maintenance_tasks_task_code_key UNIQUE (task_code);


--
-- Name: material_volume_specs material_volume_specs_factory_id_material_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.material_volume_specs
    ADD CONSTRAINT material_volume_specs_factory_id_material_code_key UNIQUE (factory_id, material_code);


--
-- Name: material_volume_specs material_volume_specs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.material_volume_specs
    ADD CONSTRAINT material_volume_specs_pkey PRIMARY KEY (id);


--
-- Name: materials materials_factory_id_material_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.materials
    ADD CONSTRAINT materials_factory_id_material_code_key UNIQUE (factory_id, material_code);


--
-- Name: materials materials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.materials
    ADD CONSTRAINT materials_pkey PRIMARY KEY (id);


--
-- Name: method_studies method_studies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.method_studies
    ADD CONSTRAINT method_studies_pkey PRIMARY KEY (id);


--
-- Name: mrp_items mrp_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mrp_items
    ADD CONSTRAINT mrp_items_pkey PRIMARY KEY (id);


--
-- Name: mrp_results mrp_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mrp_results
    ADD CONSTRAINT mrp_results_pkey PRIMARY KEY (id);


--
-- Name: mrp_runs mrp_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mrp_runs
    ADD CONSTRAINT mrp_runs_pkey PRIMARY KEY (id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: oee_daily oee_daily_factory_id_equipment_id_snapshot_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oee_daily
    ADD CONSTRAINT oee_daily_factory_id_equipment_id_snapshot_date_key UNIQUE (factory_id, equipment_id, snapshot_date);


--
-- Name: oee_daily oee_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oee_daily
    ADD CONSTRAINT oee_daily_pkey PRIMARY KEY (id);


--
-- Name: office_positions office_positions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.office_positions
    ADD CONSTRAINT office_positions_pkey PRIMARY KEY (id);


--
-- Name: online_workbooks online_workbooks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.online_workbooks
    ADD CONSTRAINT online_workbooks_pkey PRIMARY KEY (id);


--
-- Name: operators operators_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operators
    ADD CONSTRAINT operators_pkey PRIMARY KEY (id);


--
-- Name: orchestration_logs orchestration_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orchestration_logs
    ADD CONSTRAINT orchestration_logs_pkey PRIMARY KEY (id);


--
-- Name: order_decomposition_logs order_decomposition_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_decomposition_logs
    ADD CONSTRAINT order_decomposition_logs_pkey PRIMARY KEY (id);


--
-- Name: org_units org_units_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_units
    ADD CONSTRAINT org_units_pkey PRIMARY KEY (id);


--
-- Name: outbound_orders outbound_orders_outbound_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbound_orders
    ADD CONSTRAINT outbound_orders_outbound_code_key UNIQUE (outbound_code);


--
-- Name: outbound_orders outbound_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbound_orders
    ADD CONSTRAINT outbound_orders_pkey PRIMARY KEY (id);


--
-- Name: parameter_change_audit parameter_change_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parameter_change_audit
    ADD CONSTRAINT parameter_change_audit_pkey PRIMARY KEY (id);


--
-- Name: payment_requests payment_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_requests
    ADD CONSTRAINT payment_requests_pkey PRIMARY KEY (id);


--
-- Name: permissions permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_pkey PRIMARY KEY (id);


--
-- Name: personal_decisions personal_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_decisions
    ADD CONSTRAINT personal_decisions_pkey PRIMARY KEY (id);


--
-- Name: personal_knowledge personal_knowledge_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_knowledge
    ADD CONSTRAINT personal_knowledge_pkey PRIMARY KEY (id);


--
-- Name: pick_list_items pick_list_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pick_list_items
    ADD CONSTRAINT pick_list_items_pkey PRIMARY KEY (id);


--
-- Name: pick_lists pick_lists_pick_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pick_lists
    ADD CONSTRAINT pick_lists_pick_code_key UNIQUE (pick_code);


--
-- Name: pick_lists pick_lists_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pick_lists
    ADD CONSTRAINT pick_lists_pkey PRIMARY KEY (id);


--
-- Name: plan_change_requests plan_change_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plan_change_requests
    ADD CONSTRAINT plan_change_requests_pkey PRIMARY KEY (id);


--
-- Name: plans plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plans
    ADD CONSTRAINT plans_pkey PRIMARY KEY (id);


--
-- Name: pmc_changes pmc_changes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmc_changes
    ADD CONSTRAINT pmc_changes_pkey PRIMARY KEY (id);


--
-- Name: pmc_knowledge pmc_knowledge_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmc_knowledge
    ADD CONSTRAINT pmc_knowledge_pkey PRIMARY KEY (id);


--
-- Name: pmc_quiz_attempts pmc_quiz_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmc_quiz_attempts
    ADD CONSTRAINT pmc_quiz_attempts_pkey PRIMARY KEY (id);


--
-- Name: pmc_quiz_questions pmc_quiz_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmc_quiz_questions
    ADD CONSTRAINT pmc_quiz_questions_pkey PRIMARY KEY (id);


--
-- Name: pmc_quiz_questions pmc_quiz_questions_question_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmc_quiz_questions
    ADD CONSTRAINT pmc_quiz_questions_question_code_key UNIQUE (question_code);


--
-- Name: pmc_trainer_actions pmc_trainer_actions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmc_trainer_actions
    ADD CONSTRAINT pmc_trainer_actions_pkey PRIMARY KEY (id);


--
-- Name: pmc_trainer_sessions pmc_trainer_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmc_trainer_sessions
    ADD CONSTRAINT pmc_trainer_sessions_pkey PRIMARY KEY (id);


--
-- Name: position_capabilities position_capabilities_cap_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_capabilities
    ADD CONSTRAINT position_capabilities_cap_code_key UNIQUE (cap_code);


--
-- Name: position_capabilities position_capabilities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_capabilities
    ADD CONSTRAINT position_capabilities_pkey PRIMARY KEY (id);


--
-- Name: position_sops position_sops_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_sops
    ADD CONSTRAINT position_sops_pkey PRIMARY KEY (id);


--
-- Name: position_sops position_sops_position_code_industry_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_sops
    ADD CONSTRAINT position_sops_position_code_industry_code_key UNIQUE (position_code, industry_code);


--
-- Name: position_training_attempts position_training_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_training_attempts
    ADD CONSTRAINT position_training_attempts_pkey PRIMARY KEY (id);


--
-- Name: position_training_questions position_training_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_training_questions
    ADD CONSTRAINT position_training_questions_pkey PRIMARY KEY (id);


--
-- Name: position_training_questions position_training_questions_question_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_training_questions
    ADD CONSTRAINT position_training_questions_question_code_key UNIQUE (question_code);


--
-- Name: pp_plans pp_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pp_plans
    ADD CONSTRAINT pp_plans_pkey PRIMARY KEY (id);


--
-- Name: process_analyses process_analyses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.process_analyses
    ADD CONSTRAINT process_analyses_pkey PRIMARY KEY (id);


--
-- Name: process_capability process_capability_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.process_capability
    ADD CONSTRAINT process_capability_pkey PRIMARY KEY (id);


--
-- Name: process_performance process_performance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.process_performance
    ADD CONSTRAINT process_performance_pkey PRIMARY KEY (id);


--
-- Name: production_alerts_archive production_alerts_archive_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_alerts_archive
    ADD CONSTRAINT production_alerts_archive_pkey PRIMARY KEY (id);


--
-- Name: production_alerts production_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_alerts
    ADD CONSTRAINT production_alerts_pkey PRIMARY KEY (id);


--
-- Name: production_report_comments production_report_comments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_report_comments
    ADD CONSTRAINT production_report_comments_pkey PRIMARY KEY (id);


--
-- Name: production_reports production_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_reports
    ADD CONSTRAINT production_reports_pkey PRIMARY KEY (id);


--
-- Name: production_reports production_reports_report_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_reports
    ADD CONSTRAINT production_reports_report_code_key UNIQUE (report_code);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);


--
-- Name: program_work_orders program_work_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.program_work_orders
    ADD CONSTRAINT program_work_orders_pkey PRIMARY KEY (id);


--
-- Name: pull_replenishment_tasks pull_replenishment_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pull_replenishment_tasks
    ADD CONSTRAINT pull_replenishment_tasks_pkey PRIMARY KEY (id);


--
-- Name: purchase_orders purchase_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_pkey PRIMARY KEY (id);


--
-- Name: purchase_orders purchase_orders_po_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_po_code_key UNIQUE (po_code);


--
-- Name: purchase_requests purchase_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_requests
    ADD CONSTRAINT purchase_requests_pkey PRIMARY KEY (id);


--
-- Name: purchase_requisitions purchase_requisitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_requisitions
    ADD CONSTRAINT purchase_requisitions_pkey PRIMARY KEY (id);


--
-- Name: purchase_requisitions purchase_requisitions_pr_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_requisitions
    ADD CONSTRAINT purchase_requisitions_pr_code_key UNIQUE (pr_code);


--
-- Name: purchase_returns purchase_returns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_returns
    ADD CONSTRAINT purchase_returns_pkey PRIMARY KEY (id);


--
-- Name: purchase_suggestions purchase_suggestions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_suggestions
    ADD CONSTRAINT purchase_suggestions_pkey PRIMARY KEY (id);


--
-- Name: qms_8d_reports qms_8d_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qms_8d_reports
    ADD CONSTRAINT qms_8d_reports_pkey PRIMARY KEY (id);


--
-- Name: qms_8d_reports qms_8d_reports_report_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qms_8d_reports
    ADD CONSTRAINT qms_8d_reports_report_code_key UNIQUE (report_code);


--
-- Name: qms_inspection_items qms_inspection_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qms_inspection_items
    ADD CONSTRAINT qms_inspection_items_pkey PRIMARY KEY (id);


--
-- Name: qms_spc_points qms_spc_points_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qms_spc_points
    ADD CONSTRAINT qms_spc_points_pkey PRIMARY KEY (id);


--
-- Name: quality_costs quality_costs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_costs
    ADD CONSTRAINT quality_costs_pkey PRIMARY KEY (id);


--
-- Name: quality_defects quality_defects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_defects
    ADD CONSTRAINT quality_defects_pkey PRIMARY KEY (id);


--
-- Name: quality_goal_reviews quality_goal_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_goal_reviews
    ADD CONSTRAINT quality_goal_reviews_pkey PRIMARY KEY (id);


--
-- Name: quality_goals quality_goals_goal_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_goals
    ADD CONSTRAINT quality_goals_goal_code_key UNIQUE (goal_code);


--
-- Name: quality_goals quality_goals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_goals
    ADD CONSTRAINT quality_goals_pkey PRIMARY KEY (id);


--
-- Name: quality_inspections quality_inspections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_inspections
    ADD CONSTRAINT quality_inspections_pkey PRIMARY KEY (id);


--
-- Name: quality_red_tag_attachments quality_red_tag_attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_red_tag_attachments
    ADD CONSTRAINT quality_red_tag_attachments_pkey PRIMARY KEY (id);


--
-- Name: quality_red_tag quality_red_tag_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_red_tag
    ADD CONSTRAINT quality_red_tag_pkey PRIMARY KEY (id);


--
-- Name: quality_red_tag quality_red_tag_red_tag_no_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_red_tag
    ADD CONSTRAINT quality_red_tag_red_tag_no_key UNIQUE (red_tag_no);


--
-- Name: quotations quotations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotations
    ADD CONSTRAINT quotations_pkey PRIMARY KEY (id);


--
-- Name: rcc_approval_records rcc_approval_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rcc_approval_records
    ADD CONSTRAINT rcc_approval_records_pkey PRIMARY KEY (id);


--
-- Name: rcc_decision_evaluations rcc_decision_evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rcc_decision_evaluations
    ADD CONSTRAINT rcc_decision_evaluations_pkey PRIMARY KEY (id);


--
-- Name: rcc_organizations rcc_organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rcc_organizations
    ADD CONSTRAINT rcc_organizations_pkey PRIMARY KEY (id);


--
-- Name: rcc_tasks rcc_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rcc_tasks
    ADD CONSTRAINT rcc_tasks_pkey PRIMARY KEY (id);


--
-- Name: rcc_tasks rcc_tasks_task_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rcc_tasks
    ADD CONSTRAINT rcc_tasks_task_code_key UNIQUE (task_code);


--
-- Name: reconciliation_logs reconciliation_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reconciliation_logs
    ADD CONSTRAINT reconciliation_logs_pkey PRIMARY KEY (id);


--
-- Name: replenishment_thresholds replenishment_thresholds_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.replenishment_thresholds
    ADD CONSTRAINT replenishment_thresholds_pkey PRIMARY KEY (id);


--
-- Name: rfqs rfqs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rfqs
    ADD CONSTRAINT rfqs_pkey PRIMARY KEY (id);


--
-- Name: rfqs rfqs_rfq_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rfqs
    ADD CONSTRAINT rfqs_rfq_code_key UNIQUE (rfq_code);


--
-- Name: role_permissions role_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (id);


--
-- Name: role_simulation_profiles role_simulation_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_simulation_profiles
    ADD CONSTRAINT role_simulation_profiles_pkey PRIMARY KEY (role_code);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: routing_steps routing_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_steps
    ADD CONSTRAINT routing_steps_pkey PRIMARY KEY (id);


--
-- Name: routing_template_steps routing_template_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_template_steps
    ADD CONSTRAINT routing_template_steps_pkey PRIMARY KEY (id);


--
-- Name: routing_templates routing_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_templates
    ADD CONSTRAINT routing_templates_pkey PRIMARY KEY (id);


--
-- Name: routing_templates routing_templates_template_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_templates
    ADD CONSTRAINT routing_templates_template_code_key UNIQUE (template_code);


--
-- Name: routings routings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routings
    ADD CONSTRAINT routings_pkey PRIMARY KEY (id);


--
-- Name: rush_order_approval_logs rush_order_approval_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rush_order_approval_logs
    ADD CONSTRAINT rush_order_approval_logs_pkey PRIMARY KEY (id);


--
-- Name: rush_order_approvals rush_order_approvals_approval_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rush_order_approvals
    ADD CONSTRAINT rush_order_approvals_approval_code_key UNIQUE (approval_code);


--
-- Name: rush_order_approvals rush_order_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rush_order_approvals
    ADD CONSTRAINT rush_order_approvals_pkey PRIMARY KEY (id);


--
-- Name: safety_stock_config safety_stock_config_factory_id_material_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.safety_stock_config
    ADD CONSTRAINT safety_stock_config_factory_id_material_id_key UNIQUE (factory_id, material_id);


--
-- Name: safety_stock_config safety_stock_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.safety_stock_config
    ADD CONSTRAINT safety_stock_config_pkey PRIMARY KEY (id);


--
-- Name: sales_orders sales_orders_order_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales_orders
    ADD CONSTRAINT sales_orders_order_code_key UNIQUE (order_code);


--
-- Name: sales_orders sales_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales_orders
    ADD CONSTRAINT sales_orders_pkey PRIMARY KEY (id);


--
-- Name: shift_summaries shift_summaries_factory_id_shift_date_shift_type_station_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shift_summaries
    ADD CONSTRAINT shift_summaries_factory_id_shift_date_shift_type_station_id_key UNIQUE (factory_id, shift_date, shift_type, station_id, work_order_id);


--
-- Name: shift_summaries shift_summaries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shift_summaries
    ADD CONSTRAINT shift_summaries_pkey PRIMARY KEY (id);


--
-- Name: shipment_items shipment_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shipment_items
    ADD CONSTRAINT shipment_items_pkey PRIMARY KEY (id);


--
-- Name: shipments shipments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shipments
    ADD CONSTRAINT shipments_pkey PRIMARY KEY (id);


--
-- Name: shipments shipments_shipment_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shipments
    ADD CONSTRAINT shipments_shipment_code_key UNIQUE (shipment_code);


--
-- Name: sim_erp_audit_logs sim_erp_audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sim_erp_audit_logs
    ADD CONSTRAINT sim_erp_audit_logs_pkey PRIMARY KEY (id);


--
-- Name: sim_erp_audit_logs sim_erp_audit_logs_simulation_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sim_erp_audit_logs
    ADD CONSTRAINT sim_erp_audit_logs_simulation_id_key UNIQUE (simulation_id);


--
-- Name: simulation_scorecards simulation_scorecards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.simulation_scorecards
    ADD CONSTRAINT simulation_scorecards_pkey PRIMARY KEY (id);


--
-- Name: skills skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_pkey PRIMARY KEY (id);


--
-- Name: spc_chart_config spc_chart_config_factory_id_characteristic_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spc_chart_config
    ADD CONSTRAINT spc_chart_config_factory_id_characteristic_code_key UNIQUE (factory_id, characteristic_code);


--
-- Name: spc_chart_config spc_chart_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spc_chart_config
    ADD CONSTRAINT spc_chart_config_pkey PRIMARY KEY (id);


--
-- Name: spc_configs spc_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spc_configs
    ADD CONSTRAINT spc_configs_pkey PRIMARY KEY (id);


--
-- Name: standard_operation_times standard_operation_times_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.standard_operation_times
    ADD CONSTRAINT standard_operation_times_pkey PRIMARY KEY (id);


--
-- Name: station_capacity station_capacity_factory_id_station_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.station_capacity
    ADD CONSTRAINT station_capacity_factory_id_station_id_key UNIQUE (factory_id, station_id);


--
-- Name: station_capacity station_capacity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.station_capacity
    ADD CONSTRAINT station_capacity_pkey PRIMARY KEY (id);


--
-- Name: stations stations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_pkey PRIMARY KEY (id);


--
-- Name: stock_alerts stock_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stock_alerts
    ADD CONSTRAINT stock_alerts_pkey PRIMARY KEY (id);


--
-- Name: supplier_evaluations supplier_evaluations_factory_id_supplier_id_period_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplier_evaluations
    ADD CONSTRAINT supplier_evaluations_factory_id_supplier_id_period_key UNIQUE (factory_id, supplier_id, period);


--
-- Name: supplier_evaluations supplier_evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplier_evaluations
    ADD CONSTRAINT supplier_evaluations_pkey PRIMARY KEY (id);


--
-- Name: supplier_materials supplier_materials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplier_materials
    ADD CONSTRAINT supplier_materials_pkey PRIMARY KEY (id);


--
-- Name: supplier_prices supplier_prices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplier_prices
    ADD CONSTRAINT supplier_prices_pkey PRIMARY KEY (id);


--
-- Name: supplier_prices supplier_prices_supplier_id_material_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplier_prices
    ADD CONSTRAINT supplier_prices_supplier_id_material_code_key UNIQUE (supplier_id, material_code);


--
-- Name: supplier_profiles supplier_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplier_profiles
    ADD CONSTRAINT supplier_profiles_pkey PRIMARY KEY (id);


--
-- Name: suppliers suppliers_factory_id_supplier_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.suppliers
    ADD CONSTRAINT suppliers_factory_id_supplier_code_key UNIQUE (factory_id, supplier_code);


--
-- Name: suppliers suppliers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.suppliers
    ADD CONSTRAINT suppliers_pkey PRIMARY KEY (id);


--
-- Name: teams teams_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT teams_pkey PRIMARY KEY (id);


--
-- Name: time_study_records time_study_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.time_study_records
    ADD CONSTRAINT time_study_records_pkey PRIMARY KEY (id);


--
-- Name: tms_agent_actions tms_agent_actions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tms_agent_actions
    ADD CONSTRAINT tms_agent_actions_pkey PRIMARY KEY (id);


--
-- Name: tms_agent_registry tms_agent_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tms_agent_registry
    ADD CONSTRAINT tms_agent_registry_pkey PRIMARY KEY (agent_id);


--
-- Name: tms_approval_flows tms_approval_flows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tms_approval_flows
    ADD CONSTRAINT tms_approval_flows_pkey PRIMARY KEY (id);


--
-- Name: tms_approval_records tms_approval_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tms_approval_records
    ADD CONSTRAINT tms_approval_records_pkey PRIMARY KEY (id);


--
-- Name: tms_distribution_logs tms_distribution_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tms_distribution_logs
    ADD CONSTRAINT tms_distribution_logs_pkey PRIMARY KEY (id);


--
-- Name: tms_tasks tms_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tms_tasks
    ADD CONSTRAINT tms_tasks_pkey PRIMARY KEY (id);


--
-- Name: tms_webhook_subscriptions tms_webhook_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tms_webhook_subscriptions
    ADD CONSTRAINT tms_webhook_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: trainer_defects trainer_defects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trainer_defects
    ADD CONSTRAINT trainer_defects_pkey PRIMARY KEY (id);


--
-- Name: training_records training_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_records
    ADD CONSTRAINT training_records_pkey PRIMARY KEY (id);


--
-- Name: training_scenarios training_scenarios_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_scenarios
    ADD CONSTRAINT training_scenarios_pkey PRIMARY KEY (id);


--
-- Name: training_scenarios training_scenarios_scenario_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_scenarios
    ADD CONSTRAINT training_scenarios_scenario_code_key UNIQUE (scenario_code);


--
-- Name: training_sessions training_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_sessions
    ADD CONSTRAINT training_sessions_pkey PRIMARY KEY (id);


--
-- Name: aps_holidays uq_aps_holiday_factory_date; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aps_holidays
    ADD CONSTRAINT uq_aps_holiday_factory_date UNIQUE (factory_id, holiday_date);


--
-- Name: chat_events uq_chat_events_session_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_events
    ADD CONSTRAINT uq_chat_events_session_sequence UNIQUE (session_id, sequence);


--
-- Name: chat_goal_metrics uq_chat_goal_metrics_goal_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_goal_metrics
    ADD CONSTRAINT uq_chat_goal_metrics_goal_code UNIQUE (goal_id, metric_code);


--
-- Name: code_tables uq_code_table_category_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.code_tables
    ADD CONSTRAINT uq_code_table_category_code UNIQUE (category, code);


--
-- Name: replenishment_thresholds uq_rt_factory_mat_loc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.replenishment_thresholds
    ADD CONSTRAINT uq_rt_factory_mat_loc UNIQUE (factory_id, material_id, line_side_location);


--
-- Name: user_invitations user_invitations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_invitations
    ADD CONSTRAINT user_invitations_pkey PRIMARY KEY (id);


--
-- Name: user_roles user_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: vf_config vf_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vf_config
    ADD CONSTRAINT vf_config_pkey PRIMARY KEY (factory_id, key);


--
-- Name: vf_daily_snapshots vf_daily_snapshots_factory_id_snapshot_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vf_daily_snapshots
    ADD CONSTRAINT vf_daily_snapshots_factory_id_snapshot_date_key UNIQUE (factory_id, snapshot_date);


--
-- Name: vf_daily_snapshots vf_daily_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vf_daily_snapshots
    ADD CONSTRAINT vf_daily_snapshots_pkey PRIMARY KEY (id);


--
-- Name: vf_emails vf_emails_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vf_emails
    ADD CONSTRAINT vf_emails_pkey PRIMARY KEY (id);


--
-- Name: vf_events vf_events_factory_id_event_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vf_events
    ADD CONSTRAINT vf_events_factory_id_event_key_key UNIQUE (factory_id, event_key);


--
-- Name: vf_events vf_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vf_events
    ADD CONSTRAINT vf_events_pkey PRIMARY KEY (id);


--
-- Name: vf_quality_profiles vf_quality_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vf_quality_profiles
    ADD CONSTRAINT vf_quality_profiles_pkey PRIMARY KEY (profile_code);


--
-- Name: warehouses warehouses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warehouses
    ADD CONSTRAINT warehouses_pkey PRIMARY KEY (id);


--
-- Name: wms_automation_jobs wms_automation_jobs_job_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_automation_jobs
    ADD CONSTRAINT wms_automation_jobs_job_code_key UNIQUE (job_code);


--
-- Name: wms_automation_jobs wms_automation_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_automation_jobs
    ADD CONSTRAINT wms_automation_jobs_pkey PRIMARY KEY (id);


--
-- Name: wms_barcodes wms_barcodes_factory_id_barcode_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_barcodes
    ADD CONSTRAINT wms_barcodes_factory_id_barcode_key UNIQUE (factory_id, barcode);


--
-- Name: wms_barcodes wms_barcodes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_barcodes
    ADD CONSTRAINT wms_barcodes_pkey PRIMARY KEY (id);


--
-- Name: wms_inventory_pool_members wms_inventory_pool_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_inventory_pool_members
    ADD CONSTRAINT wms_inventory_pool_members_pkey PRIMARY KEY (id);


--
-- Name: wms_inventory_pool_members wms_inventory_pool_members_pool_id_warehouse_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_inventory_pool_members
    ADD CONSTRAINT wms_inventory_pool_members_pool_id_warehouse_id_key UNIQUE (pool_id, warehouse_id);


--
-- Name: wms_inventory_pools wms_inventory_pools_factory_id_pool_code_material_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_inventory_pools
    ADD CONSTRAINT wms_inventory_pools_factory_id_pool_code_material_id_key UNIQUE (factory_id, pool_code, material_id);


--
-- Name: wms_inventory_pools wms_inventory_pools_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_inventory_pools
    ADD CONSTRAINT wms_inventory_pools_pkey PRIMARY KEY (id);


--
-- Name: wms_rfid_count_items wms_rfid_count_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_rfid_count_items
    ADD CONSTRAINT wms_rfid_count_items_pkey PRIMARY KEY (id);


--
-- Name: wms_rfid_count_sessions wms_rfid_count_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_rfid_count_sessions
    ADD CONSTRAINT wms_rfid_count_sessions_pkey PRIMARY KEY (id);


--
-- Name: wms_rfid_count_sessions wms_rfid_count_sessions_session_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_rfid_count_sessions
    ADD CONSTRAINT wms_rfid_count_sessions_session_code_key UNIQUE (session_code);


--
-- Name: wms_rfid_tags wms_rfid_tags_factory_id_tag_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_rfid_tags
    ADD CONSTRAINT wms_rfid_tags_factory_id_tag_id_key UNIQUE (factory_id, tag_id);


--
-- Name: wms_rfid_tags wms_rfid_tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_rfid_tags
    ADD CONSTRAINT wms_rfid_tags_pkey PRIMARY KEY (id);


--
-- Name: wms_transfer_requests wms_transfer_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_transfer_requests
    ADD CONSTRAINT wms_transfer_requests_pkey PRIMARY KEY (id);


--
-- Name: wms_transfer_requests wms_transfer_requests_request_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_transfer_requests
    ADD CONSTRAINT wms_transfer_requests_request_code_key UNIQUE (request_code);


--
-- Name: wo_status_logs wo_status_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wo_status_logs
    ADD CONSTRAINT wo_status_logs_pkey PRIMARY KEY (id);


--
-- Name: work_cell_layouts work_cell_layouts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_cell_layouts
    ADD CONSTRAINT work_cell_layouts_pkey PRIMARY KEY (id);


--
-- Name: work_order_materials work_order_materials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_order_materials
    ADD CONSTRAINT work_order_materials_pkey PRIMARY KEY (id);


--
-- Name: work_order_pause_reasons work_order_pause_reasons_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_order_pause_reasons
    ADD CONSTRAINT work_order_pause_reasons_code_key UNIQUE (code);


--
-- Name: work_order_pause_reasons work_order_pause_reasons_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_order_pause_reasons
    ADD CONSTRAINT work_order_pause_reasons_pkey PRIMARY KEY (id);


--
-- Name: work_order_templates work_order_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_order_templates
    ADD CONSTRAINT work_order_templates_pkey PRIMARY KEY (id);


--
-- Name: work_orders work_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_pkey PRIMARY KEY (id);


--
-- Name: work_teams work_teams_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_teams
    ADD CONSTRAINT work_teams_pkey PRIMARY KEY (id);


--
-- Name: workflow_action_gates workflow_action_gates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_action_gates
    ADD CONSTRAINT workflow_action_gates_pkey PRIMARY KEY (id);


--
-- Name: workflow_rule_versions workflow_rule_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_rule_versions
    ADD CONSTRAINT workflow_rule_versions_pkey PRIMARY KEY (id);


--
-- Name: workflow_state_rules workflow_state_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_state_rules
    ADD CONSTRAINT workflow_state_rules_pkey PRIMARY KEY (id);


--
-- Name: idx_8d_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_8d_factory ON public.qms_8d_reports USING btree (factory_id, status);


--
-- Name: idx_aes_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aes_event_type ON public.andon_escalation_logs USING btree (event_type);


--
-- Name: idx_aes_ticket_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aes_ticket_created ON public.andon_escalation_logs USING btree (ticket_id, created_at);


--
-- Name: idx_agent_checkpoints_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_checkpoints_created ON public.agent_checkpoints USING btree (created_at DESC);


--
-- Name: idx_agent_checkpoints_request; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_checkpoints_request ON public.agent_checkpoints USING btree (request_id, created_at DESC);


--
-- Name: idx_agent_events_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_events_agent ON public.agent_events USING btree (agent_key, created_at DESC);


--
-- Name: idx_agent_events_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_events_factory ON public.agent_events USING btree (factory_id, created_at DESC);


--
-- Name: idx_agent_events_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_events_task ON public.agent_events USING btree (task_id);


--
-- Name: idx_agent_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_events_type ON public.agent_events USING btree (event_type);


--
-- Name: idx_ai_action_approvals_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ai_action_approvals_status ON public.ai_action_approvals USING btree (factory_id, status);


--
-- Name: idx_ai_memory_candidates_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ai_memory_candidates_status ON public.ai_memory_candidates USING btree (factory_id, status);


--
-- Name: idx_air_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_air_created ON public.alert_intelligence_reviews USING btree (created_at DESC);


--
-- Name: idx_air_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_air_factory ON public.alert_intelligence_reviews USING btree (factory_id);


--
-- Name: idx_air_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_air_source ON public.alert_intelligence_reviews USING btree (alert_source, status);


--
-- Name: idx_allowed_next; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_allowed_next ON public.workflow_state_rules USING btree (factory_id, allowed_next_state);


--
-- Name: idx_andon_assigned; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_andon_assigned ON public.andon_tickets USING btree (assigned_to);


--
-- Name: idx_andon_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_andon_category ON public.andon_tickets USING btree (category_code);


--
-- Name: idx_andon_factory_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_andon_factory_status ON public.andon_tickets USING btree (factory_id, status);


--
-- Name: idx_ap_eta; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ap_eta ON public.arrival_plans USING btree (eta_date, status);


--
-- Name: idx_aps_activity_factory_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_activity_factory_time ON public.aps_planner_activities USING btree (factory_id, started_at DESC);


--
-- Name: idx_aps_cal_resource; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_cal_resource ON public.aps_work_calendars USING btree (resource_id, day_of_week);


--
-- Name: idx_aps_holiday_factory_year; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_holiday_factory_year ON public.aps_holidays USING btree (factory_id, year);


--
-- Name: idx_aps_meeting_factory_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_meeting_factory_date ON public.aps_coordination_meetings USING btree (factory_id, meeting_date DESC);


--
-- Name: idx_aps_plan_events_factory_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_plan_events_factory_time ON public.aps_plan_events USING btree (factory_id, created_at DESC);


--
-- Name: idx_aps_plan_events_plan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_plan_events_plan ON public.aps_plan_events USING btree (plan_id, created_at DESC);


--
-- Name: idx_aps_req_retry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_req_retry ON public.aps_schedule_requests USING btree (status, retry_count);


--
-- Name: idx_aps_req_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_req_source ON public.aps_schedule_requests USING btree (source_type, source_id);


--
-- Name: idx_aps_sched_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_sched_factory ON public.aps_schedules USING btree (factory_id, status);


--
-- Name: idx_aps_sched_fp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_sched_fp ON public.aps_schedules USING btree (factory_id, input_fingerprint, horizon_start) WHERE ((status)::text = 'draft'::text);


--
-- Name: idx_aps_schedule_current; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_schedule_current ON public.aps_schedules USING btree (factory_id, is_current, created_at DESC);


--
-- Name: idx_aps_task_duration_basis; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_task_duration_basis ON public.aps_schedule_tasks USING btree (duration_basis);


--
-- Name: idx_aps_task_sched; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_task_sched ON public.aps_schedule_tasks USING btree (schedule_id);


--
-- Name: idx_aps_task_station; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_task_station ON public.aps_schedule_tasks USING btree (station_id, planned_start);


--
-- Name: idx_aps_task_wo; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aps_task_wo ON public.aps_schedule_tasks USING btree (work_order_id);


--
-- Name: idx_archive_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_archive_factory ON public.archive_records USING btree (factory_id);


--
-- Name: idx_archive_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_archive_type ON public.archive_records USING btree (record_type, archived_at);


--
-- Name: idx_awl_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_awl_agent ON public.agent_work_log USING btree (agent_key, created_at DESC);


--
-- Name: idx_awl_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_awl_ref ON public.agent_work_log USING btree (related_ref);


--
-- Name: idx_awl_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_awl_target ON public.agent_work_log USING btree (target, created_at DESC);


--
-- Name: idx_bom_items_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bom_items_factory ON public.bom_items USING btree (factory_id);


--
-- Name: idx_bom_items_material; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bom_items_material ON public.bom_items USING btree (material_code);


--
-- Name: idx_bom_items_product; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bom_items_product ON public.bom_items USING btree (product_id);


--
-- Name: idx_capa_fishbone_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_capa_fishbone_case ON public.capa_fishbone_items USING btree (case_id);


--
-- Name: idx_capa_why_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_capa_why_case ON public.capa_why_steps USING btree (case_id);


--
-- Name: idx_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_category ON public.work_order_pause_reasons USING btree (category);


--
-- Name: idx_cci_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cci_task ON public.cycle_count_items USING btree (task_id);


--
-- Name: idx_cct_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cct_factory ON public.cycle_count_tasks USING btree (factory_id, status);


--
-- Name: idx_chat_eval_cases_factory_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_eval_cases_factory_enabled ON public.chat_eval_cases USING btree (factory_id, enabled, created_at DESC);


--
-- Name: idx_chat_events_request; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_events_request ON public.chat_events USING btree (request_id, sequence);


--
-- Name: idx_chat_events_session_sequence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_events_session_sequence ON public.chat_events USING btree (session_id, sequence);


--
-- Name: idx_chat_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_events_type ON public.chat_events USING btree (event_type, created_at);


--
-- Name: idx_chat_goal_metrics_checked; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_goal_metrics_checked ON public.chat_goal_metrics USING btree (last_checked_at);


--
-- Name: idx_chat_goal_metrics_goal_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_goal_metrics_goal_status ON public.chat_goal_metrics USING btree (goal_id, status);


--
-- Name: idx_chat_goals_factory_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_goals_factory_status ON public.chat_goals USING btree (factory_id, status);


--
-- Name: idx_chat_goals_thread_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_goals_thread_status ON public.chat_goals USING btree (session_id, status);


--
-- Name: idx_chat_goals_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_goals_user ON public.chat_goals USING btree (user_id, updated_at DESC);


--
-- Name: idx_chat_memories_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_memories_user ON public.chat_memories USING btree (user_id);


--
-- Name: idx_chat_memories_user_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_chat_memories_user_key ON public.chat_memories USING btree (user_id, factory_id, key);


--
-- Name: idx_chat_messages_request; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_messages_request ON public.chat_messages USING btree (request_id);


--
-- Name: idx_chat_messages_session_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_messages_session_created ON public.chat_messages USING btree (session_id, created_at, id);


--
-- Name: idx_chat_msg_att_file; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_msg_att_file ON public.chat_message_attachments USING btree (file_id, created_at);


--
-- Name: idx_chat_msg_att_message; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_msg_att_message ON public.chat_message_attachments USING btree (message_id, ordinal);


--
-- Name: idx_chat_msg_att_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_msg_att_session ON public.chat_message_attachments USING btree (session_id, created_at);


--
-- Name: idx_chat_session_events_request; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_session_events_request ON public.chat_session_events USING btree (request_id);


--
-- Name: idx_chat_session_events_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_session_events_session ON public.chat_session_events USING btree (session_id, seq);


--
-- Name: idx_chat_sessions_factory_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_sessions_factory_user ON public.chat_sessions USING btree (factory_id, user_id, updated_at DESC);


--
-- Name: idx_chat_telemetry_failures; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_telemetry_failures ON public.chat_telemetry USING btree (success, created_at);


--
-- Name: idx_chat_telemetry_request; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_telemetry_request ON public.chat_telemetry USING btree (request_id, created_at);


--
-- Name: idx_chat_telemetry_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_telemetry_session ON public.chat_telemetry USING btree (session_id, created_at);


--
-- Name: idx_code_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_code_active ON public.work_order_pause_reasons USING btree (code, is_active);


--
-- Name: idx_code_table_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_code_table_category ON public.code_tables USING btree (category);


--
-- Name: idx_commander_cycles_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_commander_cycles_factory ON public.commander_cycles USING btree (factory_id, id DESC);


--
-- Name: idx_commander_decision_log_cycle; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_commander_decision_log_cycle ON public.commander_decision_log USING btree (cycle_id);


--
-- Name: idx_commander_decision_log_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_commander_decision_log_factory ON public.commander_decision_log USING btree (factory_id, created_at DESC);


--
-- Name: idx_commander_plans_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_commander_plans_created ON public.commander_plans USING btree (factory_id, created_at DESC);


--
-- Name: idx_commander_plans_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_commander_plans_factory ON public.commander_plans USING btree (factory_id, status);


--
-- Name: idx_count_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_count_factory ON public.inventory_counts USING btree (factory_id, status);


--
-- Name: idx_count_items; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_count_items ON public.inventory_count_items USING btree (count_id);


--
-- Name: idx_dds_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dds_factory ON public.defect_daily_summary USING btree (factory_id, summary_date);


--
-- Name: idx_dlq_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dlq_factory ON public.aps_dlq_requests USING btree (factory_id);


--
-- Name: idx_dlq_failed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dlq_failed ON public.aps_dlq_requests USING btree (failed_at);


--
-- Name: idx_downtime_eq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_downtime_eq ON public.equipment_downtime USING btree (equipment_id, start_time);


--
-- Name: idx_downtime_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_downtime_factory ON public.equipment_downtime USING btree (factory_id, start_time);


--
-- Name: idx_dr_disposition_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dr_disposition_severity ON public.defect_records USING btree (disposition, severity);


--
-- Name: idx_dr_factory_batch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dr_factory_batch ON public.defect_records USING btree (factory_id, batch_code);


--
-- Name: idx_ecn_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ecn_factory ON public.engineering_changes USING btree (factory_id, status);


--
-- Name: idx_ef_assignee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ef_assignee ON public.engineering_forms USING btree (assignee, status);


--
-- Name: idx_ef_factory_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ef_factory_type ON public.engineering_forms USING btree (factory_id, form_type, status);


--
-- Name: idx_enghub_bom_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_enghub_bom_factory ON public.enghub_bom_items USING btree (factory_id);


--
-- Name: idx_enghub_bom_factory_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_enghub_bom_factory_model ON public.enghub_bom_items USING btree (factory_id, product_model);


--
-- Name: idx_enghub_bom_model_roword; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_enghub_bom_model_roword ON public.enghub_bom_items USING btree (factory_id, product_model, original_row_number);


--
-- Name: idx_enghub_bom_sync_log_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_enghub_bom_sync_log_factory ON public.enghub_bom_sync_log USING btree (factory_id);


--
-- Name: idx_engine_loop_state_tick; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_engine_loop_state_tick ON public.engine_loop_state USING btree (last_tick_at DESC);


--
-- Name: idx_engine_loop_state_window; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_engine_loop_state_window ON public.engine_loop_state USING btree (window_started_at DESC);


--
-- Name: idx_enterprise_knowledge_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_enterprise_knowledge_category ON public.enterprise_knowledge_documents USING btree (category);


--
-- Name: idx_enterprise_knowledge_industry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_enterprise_knowledge_industry ON public.enterprise_knowledge_documents USING btree (industry_code);


--
-- Name: idx_enterprise_knowledge_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_enterprise_knowledge_role ON public.enterprise_knowledge_documents USING btree (role_code);


--
-- Name: idx_equipment_responsible_engineer; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_equipment_responsible_engineer ON public.equipment USING btree (responsible_engineer_id);


--
-- Name: idx_er_equip; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_er_equip ON public.equipment_readings USING btree (equipment_id, metric_type, recorded_at);


--
-- Name: idx_erp_inbound_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_erp_inbound_status ON public.erp_inbound USING btree (status);


--
-- Name: idx_erp_outbound_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_erp_outbound_status ON public.erp_outbound USING btree (status);


--
-- Name: idx_factory_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_factory_active ON public.workflow_rule_versions USING btree (factory_id, is_active);


--
-- Name: idx_factory_allowed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_factory_allowed ON public.workflow_state_rules USING btree (factory_id, allowed_next_state);


--
-- Name: idx_factory_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_factory_code ON public.work_order_pause_reasons USING btree (factory_id, code);


--
-- Name: idx_factory_current_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_factory_current_state ON public.workflow_state_rules USING btree (factory_id, current_state);


--
-- Name: idx_factory_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_factory_role ON public.workflow_action_gates USING btree (factory_id, required_role);


--
-- Name: idx_factory_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_factory_state ON public.workflow_state_rules USING btree (factory_id, current_state);


--
-- Name: idx_factory_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_factory_status ON public.aps_schedule_requests USING btree (factory_id, status);


--
-- Name: idx_factory_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_factory_version ON public.workflow_rule_versions USING btree (factory_id, version_number);


--
-- Name: idx_files_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_files_created ON public.files USING btree (created_at);


--
-- Name: idx_files_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_files_factory ON public.files USING btree (factory_id);


--
-- Name: idx_files_related; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_files_related ON public.files USING btree (related_type, related_id);


--
-- Name: idx_followup_assignee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_followup_assignee ON public.followup_tasks USING btree (assigned_to, status);


--
-- Name: idx_followup_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_followup_due ON public.followup_tasks USING btree (status, next_follow_at);


--
-- Name: idx_followup_factory_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_followup_factory_status ON public.followup_tasks USING btree (factory_id, status);


--
-- Name: idx_followup_item_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_followup_item_type ON public.followup_tasks USING btree (factory_id, item_type, status);


--
-- Name: idx_followup_logs_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_followup_logs_task ON public.followup_task_logs USING btree (task_id, created_at DESC);


--
-- Name: idx_followup_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_followup_owner ON public.followup_tasks USING btree (created_by, status);


--
-- Name: idx_followup_plan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_followup_plan ON public.followup_tasks USING btree (plan_id);


--
-- Name: idx_gr_material; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gr_material ON public.goods_receipts USING btree (material_code);


--
-- Name: idx_gr_po; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gr_po ON public.goods_receipts USING btree (po_id);


--
-- Name: idx_hos_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hos_date ON public.hourly_output_snapshots USING btree (factory_id, snapshot_date);


--
-- Name: idx_hr_emp_dept; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hr_emp_dept ON public.hr_employees USING btree (factory_id, department);


--
-- Name: idx_hr_emp_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hr_emp_factory ON public.hr_employees USING btree (factory_id);


--
-- Name: idx_hr_emp_skill_emp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hr_emp_skill_emp ON public.hr_employee_skills USING btree (hr_employee_id);


--
-- Name: idx_hr_emp_skill_skill; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hr_emp_skill_skill ON public.hr_employee_skills USING btree (skill_id);


--
-- Name: idx_hr_emp_station; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hr_emp_station ON public.hr_employees USING btree (factory_id, station);


--
-- Name: idx_hr_emp_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hr_emp_status ON public.hr_employees USING btree (factory_id, status);


--
-- Name: idx_ii_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ii_task ON public.inspection_items USING btree (task_id);


--
-- Name: idx_im_groups_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_im_groups_factory ON public.im_groups USING btree (factory_id);


--
-- Name: idx_im_messages_group; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_im_messages_group ON public.im_messages USING btree (group_id, created_at DESC);


--
-- Name: idx_im_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_im_status ON public.invoice_matching USING btree (status);


--
-- Name: idx_industry_knowledge_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_industry_knowledge_category ON public.industry_knowledge USING btree (category);


--
-- Name: idx_industry_knowledge_industry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_industry_knowledge_industry ON public.industry_knowledge USING btree (industry_code);


--
-- Name: idx_internal_meeting_attendees_meeting; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_internal_meeting_attendees_meeting ON public.internal_meeting_attendees USING btree (meeting_id);


--
-- Name: idx_internal_meetings_factory_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_internal_meetings_factory_time ON public.internal_meetings USING btree (factory_id, starts_at DESC);


--
-- Name: idx_inv_freeze_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_inv_freeze_factory ON public.inventory_freezes USING btree (factory_id, status);


--
-- Name: idx_inv_freeze_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_inv_freeze_until ON public.inventory_freezes USING btree (freeze_until) WHERE ((status)::text = 'active'::text);


--
-- Name: idx_inv_mat_wh_batch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_inv_mat_wh_batch ON public.inventory USING btree (material_id, warehouse_id, batch_code);


--
-- Name: idx_inv_txn; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_inv_txn ON public.inventory_transactions USING btree (factory_id, material_id, created_at);


--
-- Name: idx_inv_txn_batch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_inv_txn_batch ON public.inventory_transactions USING btree (batch_code, created_at);


--
-- Name: idx_inventory_safety; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_inventory_safety ON public.inventory USING btree (safety_stock);


--
-- Name: idx_invitation_email_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_invitation_email_factory ON public.user_invitations USING btree (email, factory_id);


--
-- Name: idx_is_primary; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_is_primary ON public.supplier_materials USING btree (is_primary);


--
-- Name: idx_it_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_it_factory ON public.inspection_tasks USING btree (factory_id, status);


--
-- Name: idx_it_factory_product; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_it_factory_product ON public.item_traceability USING btree (factory_id, product_id);


--
-- Name: idx_it_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_it_type ON public.inspection_tasks USING btree (inspect_type, status);


--
-- Name: idx_it_work_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_it_work_order ON public.item_traceability USING btree (work_order_id);


--
-- Name: idx_jctl_station; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jctl_station ON public.job_card_time_logs USING btree (factory_id, station_id, start_time);


--
-- Name: idx_jctl_wo; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jctl_wo ON public.job_card_time_logs USING btree (work_order_id);


--
-- Name: idx_loc_warehouse_zone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_loc_warehouse_zone ON public.locations USING btree (warehouse_id, zone);


--
-- Name: idx_maint_eq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maint_eq ON public.maintenance_orders USING btree (equipment_id, status);


--
-- Name: idx_maint_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maint_factory ON public.maintenance_orders USING btree (factory_id, status);


--
-- Name: idx_material_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_material_active ON public.supplier_materials USING btree (material_code, is_active);


--
-- Name: idx_material_volume_specs_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_material_volume_specs_factory ON public.material_volume_specs USING btree (factory_id);


--
-- Name: idx_mc_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mc_task ON public.maintenance_checklist USING btree (task_id);


--
-- Name: idx_mplan_eq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mplan_eq ON public.maintenance_plans USING btree (equipment_id, is_active);


--
-- Name: idx_mrp_runs_calc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mrp_runs_calc ON public.mrp_runs USING btree (calculated_at DESC);


--
-- Name: idx_mrp_runs_plan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mrp_runs_plan ON public.mrp_runs USING btree (plan_codes);


--
-- Name: idx_mt_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mt_date ON public.maintenance_tasks USING btree (planned_date, status);


--
-- Name: idx_mt_equip; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mt_equip ON public.maintenance_tasks USING btree (equipment_id, status);


--
-- Name: idx_mt_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mt_factory ON public.maintenance_tasks USING btree (factory_id, status);


--
-- Name: idx_notif_unread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notif_unread ON public.notifications USING btree (factory_id, recipient, is_read);


--
-- Name: idx_notifications_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notifications_factory ON public.notifications USING btree (factory_id);


--
-- Name: idx_notifications_recipient; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notifications_recipient ON public.notifications USING btree (recipient);


--
-- Name: idx_odl_so; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_odl_so ON public.order_decomposition_logs USING btree (sales_order_id);


--
-- Name: idx_oee_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oee_factory ON public.oee_daily USING btree (factory_id, snapshot_date);


--
-- Name: idx_online_workbooks_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_online_workbooks_factory ON public.online_workbooks USING btree (factory_id, updated_at DESC);


--
-- Name: idx_online_workbooks_source_file; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_online_workbooks_source_file ON public.online_workbooks USING btree (source_file_id);


--
-- Name: idx_op_dept; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_op_dept ON public.office_positions USING btree (department_id);


--
-- Name: idx_pa_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pa_factory ON public.production_alerts USING btree (factory_id, is_read, triggered_at);


--
-- Name: idx_pa_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pa_type ON public.production_alerts USING btree (factory_id, alert_type, triggered_at);


--
-- Name: idx_pcr_plan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pcr_plan ON public.plan_change_requests USING btree (plan_id, created_at DESC);


--
-- Name: idx_pd_employee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pd_employee ON public.personal_decisions USING btree (factory_id, employee_id);


--
-- Name: idx_perm_module_action; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_perm_module_action ON public.permissions USING btree (module, action);


--
-- Name: idx_pk_employee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pk_employee ON public.personal_knowledge USING btree (factory_id, employee_id);


--
-- Name: idx_pl_wo; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pl_wo ON public.pick_lists USING btree (work_order_id);


--
-- Name: idx_pmc_aps_activities_factory_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_aps_activities_factory_time ON public.aps_planner_activities USING btree (factory_id, started_at DESC);


--
-- Name: idx_pmc_aps_meetings_factory_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_aps_meetings_factory_date ON public.aps_coordination_meetings USING btree (factory_id, meeting_date DESC);


--
-- Name: idx_pmc_aps_plan_events_factory_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_aps_plan_events_factory_time ON public.aps_plan_events USING btree (factory_id, created_at DESC);


--
-- Name: idx_pmc_changes_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_changes_target ON public.pmc_changes USING btree (target_code, change_type);


--
-- Name: idx_pmc_changes_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_changes_time ON public.pmc_changes USING btree (created_at DESC);


--
-- Name: idx_pmc_decomposition_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_decomposition_order ON public.order_decomposition_logs USING btree (sales_order_id);


--
-- Name: idx_pmc_ecn_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_ecn_factory ON public.engineering_changes USING btree (factory_id, status);


--
-- Name: idx_pmc_mrp_items_material; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_mrp_items_material ON public.mrp_items USING btree (material_code);


--
-- Name: idx_pmc_mrp_items_result; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_mrp_items_result ON public.mrp_items USING btree (mrp_result_id);


--
-- Name: idx_pmc_mrp_results_plan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_mrp_results_plan ON public.mrp_results USING btree (plan_id, calculated_at DESC);


--
-- Name: idx_pmc_purchase_orders_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_purchase_orders_factory ON public.purchase_orders USING btree (factory_id, status);


--
-- Name: idx_pmc_purchase_orders_supplier; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_purchase_orders_supplier ON public.purchase_orders USING btree (supplier_id);


--
-- Name: idx_pmc_purchase_requisitions_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_purchase_requisitions_factory ON public.purchase_requisitions USING btree (factory_id, status);


--
-- Name: idx_pmc_purchase_suggestions_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_purchase_suggestions_factory ON public.purchase_suggestions USING btree (factory_id, status);


--
-- Name: idx_pmc_purchase_suggestions_material; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_purchase_suggestions_material ON public.purchase_suggestions USING btree (material_code);


--
-- Name: idx_pmc_quiz_attempts_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_quiz_attempts_user ON public.pmc_quiz_attempts USING btree (user_id, created_at DESC);


--
-- Name: idx_pmc_sales_orders_delivery; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_sales_orders_delivery ON public.sales_orders USING btree (factory_id, delivery_date);


--
-- Name: idx_pmc_sales_orders_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_sales_orders_factory ON public.sales_orders USING btree (factory_id, status);


--
-- Name: idx_pmc_sales_orders_ship_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_sales_orders_ship_date ON public.sales_orders USING btree (factory_id, actual_ship_date);


--
-- Name: idx_pmc_station_capacity_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_station_capacity_factory ON public.station_capacity USING btree (factory_id);


--
-- Name: idx_pmc_station_capacity_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_station_capacity_source ON public.station_capacity USING btree (factory_id, source);


--
-- Name: idx_pmc_supplier_material_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_supplier_material_code ON public.supplier_materials USING btree (material_code, is_active);


--
-- Name: idx_pmc_supplier_prices_material; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_supplier_prices_material ON public.supplier_prices USING btree (material_code, is_active);


--
-- Name: idx_pmc_suppliers_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pmc_suppliers_factory ON public.suppliers USING btree (factory_id);


--
-- Name: idx_po_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_po_factory ON public.purchase_orders USING btree (factory_id, status);


--
-- Name: idx_po_supplier; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_po_supplier ON public.purchase_orders USING btree (supplier_id);


--
-- Name: idx_position_sops_industry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_sops_industry ON public.position_sops USING btree (industry_code);


--
-- Name: idx_position_sops_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_sops_position ON public.position_sops USING btree (position_code);


--
-- Name: idx_position_training_attempts_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_training_attempts_user ON public.position_training_attempts USING btree (position_code, user_id, created_at DESC);


--
-- Name: idx_position_training_questions; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_training_questions ON public.position_training_questions USING btree (position_code, is_active, difficulty);


--
-- Name: idx_pp_plans_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pp_plans_factory ON public.pp_plans USING btree (factory_id);


--
-- Name: idx_pp_plans_product; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pp_plans_product ON public.pp_plans USING btree (product_id);


--
-- Name: idx_pp_plans_required_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pp_plans_required_date ON public.pp_plans USING btree (required_date);


--
-- Name: idx_pp_plans_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pp_plans_status ON public.pp_plans USING btree (status);


--
-- Name: idx_pp_plans_work_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pp_plans_work_order ON public.pp_plans USING btree (work_order_id);


--
-- Name: idx_pr_batch_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_batch_code ON public.production_reports USING btree (batch_code);


--
-- Name: idx_pr_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_factory ON public.purchase_requisitions USING btree (factory_id, status);


--
-- Name: idx_pr_factory_material; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_factory_material ON public.purchase_requisitions USING btree (factory_id, material_id);


--
-- Name: idx_pr_factory_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_factory_status ON public.purchase_requisitions USING btree (factory_id, status);


--
-- Name: idx_pr_operator_skill; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_operator_skill ON public.production_reports USING btree (operator_skill_level);


--
-- Name: idx_pr_qc_gate; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_qc_gate ON public.production_reports USING btree (qc_gate_passed, factory_id);


--
-- Name: idx_pr_shift; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_shift ON public.production_reports USING btree (factory_id, shift, created_at);


--
-- Name: idx_pr_station_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_station_time ON public.production_reports USING btree (factory_id, station_id, created_at);


--
-- Name: idx_pr_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_status ON public.purchase_requisitions USING btree (status);


--
-- Name: idx_pr_suggested_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_suggested_date ON public.purchase_requisitions USING btree (suggested_date);


--
-- Name: idx_pr_tool_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_tool_id ON public.production_reports USING btree (tool_id);


--
-- Name: idx_pr_work_order_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_work_order_created ON public.production_reports USING btree (work_order_id, created_at);


--
-- Name: idx_prt_factory_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_prt_factory_status ON public.pull_replenishment_tasks USING btree (factory_id, status);


--
-- Name: idx_pwo_factory_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pwo_factory_status ON public.program_work_orders USING btree (factory_id, status);


--
-- Name: idx_pwo_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pwo_template ON public.program_work_orders USING btree (template_code);


--
-- Name: idx_qg_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qg_factory ON public.quality_goals USING btree (factory_id, status);


--
-- Name: idx_qii_inspection; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qii_inspection ON public.qms_inspection_items USING btree (inspection_id);


--
-- Name: idx_quick_cmd_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_quick_cmd_factory ON public.chat_quick_commands USING btree (factory_id, sort_order);


--
-- Name: idx_quot_rfq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_quot_rfq ON public.quotations USING btree (rfq_id);


--
-- Name: idx_rcc_eval_factory_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rcc_eval_factory_status ON public.rcc_decision_evaluations USING btree (factory_id, status);


--
-- Name: idx_rcc_eval_next; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rcc_eval_next ON public.rcc_decision_evaluations USING btree (next_evaluate_at);


--
-- Name: idx_rcc_tasks_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rcc_tasks_factory_id ON public.rcc_tasks USING btree (factory_id);


--
-- Name: idx_real_bom_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_real_bom_model ON public.enghub_bom_items USING btree (product_model);


--
-- Name: idx_real_bom_part; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_real_bom_part ON public.enghub_bom_items USING btree (part_number);


--
-- Name: idx_red_tag_attachment_file; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_red_tag_attachment_file ON public.quality_red_tag_attachments USING btree (file_id);


--
-- Name: idx_red_tag_attachment_red_tag; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_red_tag_attachment_red_tag ON public.quality_red_tag_attachments USING btree (red_tag_id);


--
-- Name: idx_red_tag_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_red_tag_created_at ON public.quality_red_tag USING btree (created_at);


--
-- Name: idx_red_tag_defect; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_red_tag_defect ON public.quality_red_tag USING btree (defect_id);


--
-- Name: idx_red_tag_disposition; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_red_tag_disposition ON public.quality_red_tag USING btree (disposition);


--
-- Name: idx_red_tag_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_red_tag_factory ON public.quality_red_tag USING btree (factory_id);


--
-- Name: idx_red_tag_no; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_red_tag_no ON public.quality_red_tag USING btree (red_tag_no);


--
-- Name: idx_red_tag_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_red_tag_status ON public.quality_red_tag USING btree (quarantine_status);


--
-- Name: idx_red_tag_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_red_tag_type ON public.quality_red_tag USING btree (red_tag_type);


--
-- Name: idx_rfq_material; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rfq_material ON public.rfqs USING btree (material_code, status);


--
-- Name: idx_rl_factory_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rl_factory_date ON public.reconciliation_logs USING btree (factory_id, checked_at);


--
-- Name: idx_rl_work_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rl_work_order ON public.reconciliation_logs USING btree (work_order_id, status);


--
-- Name: idx_roa_applicant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_roa_applicant ON public.rush_order_approvals USING btree (applicant);


--
-- Name: idx_roa_factory_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_roa_factory_status ON public.rush_order_approvals USING btree (factory_id, status);


--
-- Name: idx_roa_required_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_roa_required_role ON public.rush_order_approvals USING btree (required_role);


--
-- Name: idx_roal_approval_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_roal_approval_id ON public.rush_order_approval_logs USING btree (approval_id);


--
-- Name: idx_role_perm_role_perm; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_role_perm_role_perm ON public.role_permissions USING btree (role_id, permission_id);


--
-- Name: idx_role_position_dept; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_role_position_dept ON public.roles USING btree ("position", department);


--
-- Name: idx_role_simulation_family; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_role_simulation_family ON public.role_simulation_profiles USING btree (role_family);


--
-- Name: idx_rt_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rt_factory ON public.routing_templates USING btree (factory_id);


--
-- Name: idx_rts_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rts_template ON public.routing_template_steps USING btree (template_id, seq);


--
-- Name: idx_sa_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sa_factory ON public.stock_alerts USING btree (factory_id, status);


--
-- Name: idx_sa_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sa_type ON public.stock_alerts USING btree (alert_type, status);


--
-- Name: idx_sc_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sc_factory ON public.station_capacity USING btree (factory_id);


--
-- Name: idx_scc_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scc_factory ON public.spc_chart_config USING btree (factory_id);


--
-- Name: idx_se_supplier; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_se_supplier ON public.supplier_evaluations USING btree (supplier_id, period);


--
-- Name: idx_ship_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ship_factory ON public.shipments USING btree (factory_id, plan_date DESC);


--
-- Name: idx_ship_items; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ship_items ON public.shipment_items USING btree (shipment_id);


--
-- Name: idx_sim_erp_simulation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sim_erp_simulation_id ON public.sim_erp_audit_logs USING btree (simulation_id);


--
-- Name: idx_sim_erp_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sim_erp_status_created ON public.sim_erp_audit_logs USING btree (final_status, created_at DESC);


--
-- Name: idx_sim_erp_worker_shift; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sim_erp_worker_shift ON public.sim_erp_audit_logs USING btree (worker_ref, shift_id);


--
-- Name: idx_sim_scorecards_factory_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sim_scorecards_factory_time ON public.simulation_scorecards USING btree (factory_id, engine_date DESC);


--
-- Name: idx_so_delivery; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_so_delivery ON public.sales_orders USING btree (factory_id, delivery_date);


--
-- Name: idx_so_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_so_factory ON public.sales_orders USING btree (factory_id, status);


--
-- Name: idx_so_product; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_so_product ON public.sales_orders USING btree (product_id);


--
-- Name: idx_sp_material; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sp_material ON public.supplier_prices USING btree (material_code, is_active);


--
-- Name: idx_spc_char; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_spc_char ON public.qms_spc_points USING btree (factory_id, characteristic_code, measured_at);


--
-- Name: idx_ss_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ss_date ON public.shift_summaries USING btree (factory_id, shift_date);


--
-- Name: idx_ss_station; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ss_station ON public.shift_summaries USING btree (factory_id, station_id, shift_date);


--
-- Name: idx_ssc_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ssc_factory ON public.safety_stock_config USING btree (factory_id);


--
-- Name: idx_supplier_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_supplier_category ON public.suppliers USING btree (factory_id, category);


--
-- Name: idx_supplier_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_supplier_code ON public.suppliers USING btree (supplier_code);


--
-- Name: idx_supplier_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_supplier_factory ON public.suppliers USING btree (factory_id);


--
-- Name: idx_supplier_material; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_supplier_material ON public.supplier_materials USING btree (supplier_id, material_code);


--
-- Name: idx_supplier_search; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_supplier_search ON public.suppliers USING btree (upper((supplier_name)::text));


--
-- Name: idx_supplier_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_supplier_status ON public.suppliers USING btree (is_active);


--
-- Name: idx_tms_agent_action_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tms_agent_action_type ON public.tms_agent_actions USING btree (agent_id, action_type);


--
-- Name: idx_tms_approval_flow_step; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tms_approval_flow_step ON public.tms_approval_records USING btree (flow_id, step_index);


--
-- Name: idx_tms_task_assigned; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tms_task_assigned ON public.tms_tasks USING btree (assigned_to, status);


--
-- Name: idx_tms_task_status_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tms_task_status_priority ON public.tms_tasks USING btree (status, priority);


--
-- Name: idx_tms_task_type_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tms_task_type_status ON public.tms_tasks USING btree (task_type, status);


--
-- Name: idx_trainer_defects_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trainer_defects_session ON public.trainer_defects USING btree (session_id);


--
-- Name: idx_trainer_defects_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trainer_defects_status ON public.trainer_defects USING btree (status);


--
-- Name: idx_training_scenarios_industry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_training_scenarios_industry ON public.training_scenarios USING btree (industry_code);


--
-- Name: idx_training_scenarios_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_training_scenarios_position ON public.training_scenarios USING btree (position_code);


--
-- Name: idx_training_sessions_scenario; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_training_sessions_scenario ON public.training_sessions USING btree (scenario_id);


--
-- Name: idx_training_sessions_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_training_sessions_user ON public.training_sessions USING btree (user_id);


--
-- Name: idx_user_factory_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_factory_role ON public.users USING btree (factory_id, role);


--
-- Name: idx_user_password_reset_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_password_reset_token ON public.users USING btree (password_reset_token);


--
-- Name: idx_user_role_user_role; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_user_role_user_role ON public.user_roles USING btree (user_id, role_id);


--
-- Name: idx_users_work_center; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_users_work_center ON public.users USING btree (work_center);


--
-- Name: idx_wh_factory_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wh_factory_type ON public.warehouses USING btree (factory_id, warehouse_type);


--
-- Name: idx_wms_auto_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wms_auto_factory ON public.wms_automation_jobs USING btree (factory_id, status);


--
-- Name: idx_wms_barcode_mat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wms_barcode_mat ON public.wms_barcodes USING btree (factory_id, material_code);


--
-- Name: idx_wms_xfer_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wms_xfer_factory ON public.wms_transfer_requests USING btree (factory_id, status);


--
-- Name: idx_wo_assigned_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wo_assigned_to ON public.work_orders USING btree (assigned_to);


--
-- Name: idx_wo_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wo_parent ON public.work_orders USING btree (parent_work_order_id);


--
-- Name: idx_wo_pause_reason; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wo_pause_reason ON public.work_orders USING btree (pause_reason_id);


--
-- Name: idx_wo_process_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wo_process_code ON public.work_orders USING btree (process_code);


--
-- Name: idx_wo_reservation_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wo_reservation_status ON public.work_orders USING btree (status, reserved_qty) WHERE ((status)::text = ANY (ARRAY[('released'::character varying)::text, ('in_progress'::character varying)::text, ('pending_inbound'::character varying)::text]));


--
-- Name: idx_wo_reserved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wo_reserved ON public.work_orders USING btree (reserved_warehouse, reserved_qty);


--
-- Name: idx_wo_status_logs_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wo_status_logs_created ON public.wo_status_logs USING btree (created_at);


--
-- Name: idx_wo_status_logs_wo; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wo_status_logs_wo ON public.wo_status_logs USING btree (work_order_id);


--
-- Name: idx_wo_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wo_type ON public.work_orders USING btree (wo_type);


--
-- Name: idx_wo_work_center; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wo_work_center ON public.work_orders USING btree (work_center);


--
-- Name: idx_work_order_materials_work_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_work_order_materials_work_order ON public.work_order_materials USING btree (work_order_id);


--
-- Name: idx_work_orders_source_plan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_work_orders_source_plan ON public.work_orders USING btree (source_plan_id);


--
-- Name: ix_attendance_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attendance_date ON public.attendance USING btree (date);


--
-- Name: ix_attendance_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attendance_factory_id ON public.attendance USING btree (factory_id);


--
-- Name: ix_attendance_operator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attendance_operator_id ON public.attendance USING btree (operator_id);


--
-- Name: ix_decision_records_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_decision_records_lookup ON public.decision_records USING btree (factory_id, occurred_at DESC);


--
-- Name: ix_defect_records_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_defect_records_factory_id ON public.defect_records USING btree (factory_id);


--
-- Name: ix_defect_records_is_finalized; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_defect_records_is_finalized ON public.defect_records USING btree (is_finalized);


--
-- Name: ix_defect_records_ocap_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_defect_records_ocap_status ON public.defect_records USING btree (ocap_status);


--
-- Name: ix_defect_records_product_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_defect_records_product_id ON public.defect_records USING btree (product_id);


--
-- Name: ix_defect_records_production_report_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_defect_records_production_report_id ON public.defect_records USING btree (production_report_id);


--
-- Name: ix_defect_records_record_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_defect_records_record_code ON public.defect_records USING btree (record_code);


--
-- Name: ix_defect_records_station_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_defect_records_station_id ON public.defect_records USING btree (station_id);


--
-- Name: ix_defect_records_work_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_defect_records_work_order_id ON public.defect_records USING btree (work_order_id);


--
-- Name: ix_departments_dept_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_departments_dept_code ON public.departments USING btree (dept_code);


--
-- Name: ix_departments_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_departments_factory_id ON public.departments USING btree (factory_id);


--
-- Name: ix_employee_skills_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_employee_skills_id ON public.employee_skills USING btree (id);


--
-- Name: ix_employee_skills_skill_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_employee_skills_skill_id ON public.employee_skills USING btree (skill_id);


--
-- Name: ix_employee_skills_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_employee_skills_user_id ON public.employee_skills USING btree (user_id);


--
-- Name: ix_equipment_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_equipment_factory_id ON public.equipment USING btree (factory_id);


--
-- Name: ix_equipment_station_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_equipment_station_id ON public.equipment USING btree (station_id);


--
-- Name: ix_execution_events_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_execution_events_lookup ON public.execution_events USING btree (factory_id, action, occurred_at DESC);


--
-- Name: ix_factory_rules_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_factory_rules_lookup ON public.factory_rules USING btree (factory_id, subject, status);


--
-- Name: ix_inbound_orders_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inbound_orders_factory_id ON public.inbound_orders USING btree (factory_id);


--
-- Name: ix_inbound_orders_production_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inbound_orders_production_order_id ON public.inbound_orders USING btree (production_order_id);


--
-- Name: ix_inventory_batch_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_batch_code ON public.inventory USING btree (batch_code);


--
-- Name: ix_inventory_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_factory_id ON public.inventory USING btree (factory_id);


--
-- Name: ix_inventory_material_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_material_id ON public.inventory USING btree (material_id);


--
-- Name: ix_inventory_warehouse_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_warehouse_id ON public.inventory USING btree (warehouse_id);


--
-- Name: ix_item_traceability_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_traceability_factory_id ON public.item_traceability USING btree (factory_id);


--
-- Name: ix_item_traceability_item_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_traceability_item_type ON public.item_traceability USING btree (item_type);


--
-- Name: ix_item_traceability_material_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_traceability_material_batch_id ON public.item_traceability USING btree (material_batch_id);


--
-- Name: ix_item_traceability_operator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_traceability_operator_id ON public.item_traceability USING btree (operator_id);


--
-- Name: ix_item_traceability_product_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_traceability_product_id ON public.item_traceability USING btree (product_id);


--
-- Name: ix_item_traceability_serial_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_traceability_serial_number ON public.item_traceability USING btree (serial_number);


--
-- Name: ix_item_traceability_station_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_traceability_station_id ON public.item_traceability USING btree (station_id);


--
-- Name: ix_item_traceability_work_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_traceability_work_order_id ON public.item_traceability USING btree (work_order_id);


--
-- Name: ix_job_dispatches_routing_step_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_job_dispatches_routing_step_id ON public.job_dispatches USING btree (routing_step_id);


--
-- Name: ix_job_dispatches_work_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_job_dispatches_work_order_id ON public.job_dispatches USING btree (work_order_id);


--
-- Name: ix_locations_location_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_locations_location_code ON public.locations USING btree (location_code);


--
-- Name: ix_locations_warehouse_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_locations_warehouse_id ON public.locations USING btree (warehouse_id);


--
-- Name: ix_login_attempts_user_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_login_attempts_user_time ON public.login_attempts USING btree (username, attempted_at);


--
-- Name: ix_notifications_fid_cat_read_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_fid_cat_read_created ON public.notifications USING btree (factory_id, category, is_read, created_at);


--
-- Name: ix_notifications_unread_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_unread_source ON public.notifications USING btree (source_type, source_id) WHERE (is_read = false);


--
-- Name: ix_operators_employee_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_operators_employee_id ON public.operators USING btree (employee_id);


--
-- Name: ix_operators_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_operators_factory_id ON public.operators USING btree (factory_id);


--
-- Name: ix_order_prediction_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_order_prediction_factory ON public.engine_order_predictions USING btree (factory_id, made_on DESC);


--
-- Name: ix_order_prediction_paired; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_order_prediction_paired ON public.engine_order_predictions USING btree (factory_id, paired_on DESC);


--
-- Name: ix_outbound_orders_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbound_orders_factory_id ON public.outbound_orders USING btree (factory_id);


--
-- Name: ix_outbound_orders_sales_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbound_orders_sales_order_id ON public.outbound_orders USING btree (sales_order_id);


--
-- Name: ix_outbound_orders_work_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbound_orders_work_order_id ON public.outbound_orders USING btree (work_order_id);


--
-- Name: ix_permissions_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_permissions_action ON public.permissions USING btree (action);


--
-- Name: ix_permissions_module; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_permissions_module ON public.permissions USING btree (module);


--
-- Name: ix_plans_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_plans_factory_id ON public.plans USING btree (factory_id);


--
-- Name: ix_plans_plan_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_plans_plan_code ON public.plans USING btree (plan_code);


--
-- Name: ix_plans_product_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_plans_product_id ON public.plans USING btree (product_id);


--
-- Name: ix_pmc_knowledge_cat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pmc_knowledge_cat ON public.pmc_knowledge USING btree (category);


--
-- Name: ix_process_performance_routing_step_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_process_performance_routing_step_id ON public.process_performance USING btree (routing_step_id);


--
-- Name: ix_process_performance_station_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_process_performance_station_id ON public.process_performance USING btree (station_id);


--
-- Name: ix_process_performance_work_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_process_performance_work_order_id ON public.process_performance USING btree (work_order_id);


--
-- Name: ix_production_report_comments_report_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_production_report_comments_report_id ON public.production_report_comments USING btree (report_id);


--
-- Name: ix_production_reports_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_production_reports_factory_id ON public.production_reports USING btree (factory_id);


--
-- Name: ix_production_reports_station_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_production_reports_station_id ON public.production_reports USING btree (station_id);


--
-- Name: ix_production_reports_work_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_production_reports_work_order_id ON public.production_reports USING btree (work_order_id);


--
-- Name: ix_products_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_products_factory_id ON public.products USING btree (factory_id);


--
-- Name: ix_products_product_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_products_product_code ON public.products USING btree (product_code);


--
-- Name: ix_pull_replenishment_tasks_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pull_replenishment_tasks_factory_id ON public.pull_replenishment_tasks USING btree (factory_id);


--
-- Name: ix_pull_replenishment_tasks_material_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pull_replenishment_tasks_material_id ON public.pull_replenishment_tasks USING btree (material_id);


--
-- Name: ix_pull_replenishment_tasks_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pull_replenishment_tasks_status ON public.pull_replenishment_tasks USING btree (status);


--
-- Name: ix_pull_replenishment_tasks_task_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_pull_replenishment_tasks_task_code ON public.pull_replenishment_tasks USING btree (task_code);


--
-- Name: ix_quality_inspections_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quality_inspections_factory_id ON public.quality_inspections USING btree (factory_id);


--
-- Name: ix_quality_inspections_routing_step_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quality_inspections_routing_step_id ON public.quality_inspections USING btree (routing_step_id);


--
-- Name: ix_quality_inspections_work_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quality_inspections_work_order_id ON public.quality_inspections USING btree (work_order_id);


--
-- Name: ix_reconciliation_logs_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reconciliation_logs_factory_id ON public.reconciliation_logs USING btree (factory_id);


--
-- Name: ix_reconciliation_logs_reconcile_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_reconciliation_logs_reconcile_code ON public.reconciliation_logs USING btree (reconcile_code);


--
-- Name: ix_reconciliation_logs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reconciliation_logs_status ON public.reconciliation_logs USING btree (status);


--
-- Name: ix_reconciliation_logs_work_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reconciliation_logs_work_order_id ON public.reconciliation_logs USING btree (work_order_id);


--
-- Name: ix_replenishment_thresholds_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_replenishment_thresholds_factory_id ON public.replenishment_thresholds USING btree (factory_id);


--
-- Name: ix_replenishment_thresholds_material_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_replenishment_thresholds_material_id ON public.replenishment_thresholds USING btree (material_id);


--
-- Name: ix_role_permissions_permission_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_permissions_permission_id ON public.role_permissions USING btree (permission_id);


--
-- Name: ix_role_permissions_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_permissions_role_id ON public.role_permissions USING btree (role_id);


--
-- Name: ix_roles_is_system; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_roles_is_system ON public.roles USING btree (is_system);


--
-- Name: ix_roles_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_roles_position ON public.roles USING btree ("position");


--
-- Name: ix_roles_role_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_roles_role_code ON public.roles USING btree (role_code);


--
-- Name: ix_routing_steps_dept_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_routing_steps_dept_id ON public.routing_steps USING btree (dept_id);


--
-- Name: ix_routing_steps_routing_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_routing_steps_routing_id ON public.routing_steps USING btree (routing_id);


--
-- Name: ix_routings_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_routings_factory_id ON public.routings USING btree (factory_id);


--
-- Name: ix_routings_product_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_routings_product_id ON public.routings USING btree (product_id);


--
-- Name: ix_skills_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skills_category ON public.skills USING btree (category);


--
-- Name: ix_skills_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_skills_code ON public.skills USING btree (code);


--
-- Name: ix_skills_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skills_id ON public.skills USING btree (id);


--
-- Name: ix_stations_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_stations_factory_id ON public.stations USING btree (factory_id);


--
-- Name: ix_stations_station_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_stations_station_code ON public.stations USING btree (station_code);


--
-- Name: ix_teams_dept_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_teams_dept_id ON public.teams USING btree (dept_id);


--
-- Name: ix_teams_team_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_teams_team_code ON public.teams USING btree (team_code);


--
-- Name: ix_tms_agent_actions_action_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tms_agent_actions_action_type ON public.tms_agent_actions USING btree (action_type);


--
-- Name: ix_tms_agent_actions_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tms_agent_actions_agent_id ON public.tms_agent_actions USING btree (agent_id);


--
-- Name: ix_tms_agent_actions_idempotency_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_tms_agent_actions_idempotency_key ON public.tms_agent_actions USING btree (idempotency_key);


--
-- Name: ix_tms_agent_actions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tms_agent_actions_status ON public.tms_agent_actions USING btree (status);


--
-- Name: ix_tms_approval_flows_flow_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_tms_approval_flows_flow_code ON public.tms_approval_flows USING btree (flow_code);


--
-- Name: ix_tms_approval_flows_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tms_approval_flows_status ON public.tms_approval_flows USING btree (status);


--
-- Name: ix_tms_approval_flows_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tms_approval_flows_task_id ON public.tms_approval_flows USING btree (task_id);


--
-- Name: ix_tms_approval_records_flow_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tms_approval_records_flow_id ON public.tms_approval_records USING btree (flow_id);


--
-- Name: ix_tms_distribution_logs_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tms_distribution_logs_task_id ON public.tms_distribution_logs USING btree (task_id);


--
-- Name: ix_tms_tasks_assigned_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tms_tasks_assigned_to ON public.tms_tasks USING btree (assigned_to);


--
-- Name: ix_tms_tasks_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tms_tasks_priority ON public.tms_tasks USING btree (priority);


--
-- Name: ix_tms_tasks_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tms_tasks_status ON public.tms_tasks USING btree (status);


--
-- Name: ix_tms_tasks_task_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_tms_tasks_task_code ON public.tms_tasks USING btree (task_code);


--
-- Name: ix_tms_tasks_task_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tms_tasks_task_type ON public.tms_tasks USING btree (task_type);


--
-- Name: ix_tms_webhook_subscriptions_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tms_webhook_subscriptions_agent_id ON public.tms_webhook_subscriptions USING btree (agent_id);


--
-- Name: ix_trainer_actions_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_trainer_actions_session ON public.pmc_trainer_actions USING btree (session_id);


--
-- Name: ix_training_records_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_records_id ON public.training_records USING btree (id);


--
-- Name: ix_training_records_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_records_user_id ON public.training_records USING btree (user_id);


--
-- Name: ix_user_invitations_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_invitations_email ON public.user_invitations USING btree (email);


--
-- Name: ix_user_invitations_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_invitations_factory_id ON public.user_invitations USING btree (factory_id);


--
-- Name: ix_user_invitations_token; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_user_invitations_token ON public.user_invitations USING btree (token);


--
-- Name: ix_user_roles_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_roles_role_id ON public.user_roles USING btree (role_id);


--
-- Name: ix_user_roles_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_roles_user_id ON public.user_roles USING btree (user_id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_factory_id ON public.users USING btree (factory_id);


--
-- Name: ix_users_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_role ON public.users USING btree (role);


--
-- Name: ix_users_username; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_username ON public.users USING btree (username);


--
-- Name: ix_vf_emails_factory_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vf_emails_factory_time ON public.vf_emails USING btree (factory_id, sent_at DESC);


--
-- Name: ix_vf_emails_thread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vf_emails_thread ON public.vf_emails USING btree (factory_id, thread_key, sent_at);


--
-- Name: ix_vf_events_factory_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vf_events_factory_time ON public.vf_events USING btree (factory_id, occurred_at DESC);


--
-- Name: ix_vf_events_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vf_events_source ON public.vf_events USING btree (source_type, source_id);


--
-- Name: ix_vf_quality_profiles_factory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vf_quality_profiles_factory ON public.vf_quality_profiles USING btree (factory_id, is_active);


--
-- Name: ix_warehouses_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_warehouses_factory_id ON public.warehouses USING btree (factory_id);


--
-- Name: ix_warehouses_warehouse_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_warehouses_warehouse_code ON public.warehouses USING btree (warehouse_code);


--
-- Name: ix_wo_status_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wo_status_logs_created_at ON public.wo_status_logs USING btree (created_at);


--
-- Name: ix_wo_status_logs_work_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_wo_status_logs_work_order_id ON public.wo_status_logs USING btree (work_order_id);


--
-- Name: ix_work_orders_factory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_orders_factory_id ON public.work_orders USING btree (factory_id);


--
-- Name: ix_work_orders_plan_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_orders_plan_id ON public.work_orders USING btree (plan_id);


--
-- Name: ix_work_orders_product_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_orders_product_id ON public.work_orders USING btree (product_id);


--
-- Name: ix_work_orders_work_order_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_work_orders_work_order_code ON public.work_orders USING btree (work_order_code);


--
-- Name: production_alerts_archive_factory_id_alert_type_triggered_a_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX production_alerts_archive_factory_id_alert_type_triggered_a_idx ON public.production_alerts_archive USING btree (factory_id, alert_type, triggered_at);


--
-- Name: production_alerts_archive_factory_id_is_read_triggered_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX production_alerts_archive_factory_id_is_read_triggered_at_idx ON public.production_alerts_archive USING btree (factory_id, is_read, triggered_at);


--
-- Name: uniq_factory_curr_next; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uniq_factory_curr_next ON public.workflow_state_rules USING btree (factory_id, current_state, allowed_next_state);


--
-- Name: uniq_supplier_material; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uniq_supplier_material ON public.supplier_materials USING btree (supplier_id, material_code);


--
-- Name: uniq_work_order_pause_reasons_factory_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uniq_work_order_pause_reasons_factory_code ON public.work_order_pause_reasons USING btree (factory_id, code);


--
-- Name: uniq_workflow_rule_versions_factory_version; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uniq_workflow_rule_versions_factory_version ON public.workflow_rule_versions USING btree (factory_id, version_number);


--
-- Name: uq_aps_schedule_one_current; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_aps_schedule_one_current ON public.aps_schedules USING btree (factory_id) WHERE (is_current = true);


--
-- Name: uq_bom_items_row_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_bom_items_row_id ON public.bom_items USING btree (row_id);


--
-- Name: uq_cost_parameters_factory_item; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_cost_parameters_factory_item ON public.cost_parameters USING btree (COALESCE(factory_id, '*'::character varying), item_code);


--
-- Name: uq_enghub_bom_factory_source; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_enghub_bom_factory_source ON public.enghub_bom_items USING btree (factory_id, source_row_id) WHERE ((factory_id IS NOT NULL) AND (source_row_id IS NOT NULL));


--
-- Name: uq_im_group_members_group_user; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_im_group_members_group_user ON public.im_group_members USING btree (group_id, user_id) WHERE ((group_id IS NOT NULL) AND (user_id IS NOT NULL));


--
-- Name: uq_line_profiles_factory_line; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_line_profiles_factory_line ON public.line_profiles USING btree (factory_id, line_code);


--
-- Name: uq_order_prediction_day; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_order_prediction_day ON public.engine_order_predictions USING btree (work_order_id, made_on, basis);


--
-- Name: uq_purchase_requisitions_purchase_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_purchase_requisitions_purchase_code ON public.purchase_requisitions USING btree (purchase_code);


--
-- Name: uq_roles_role_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_roles_role_code ON public.roles USING btree (role_code);


--
-- Name: uq_suppliers_supplier_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_suppliers_supplier_code ON public.suppliers USING btree (supplier_code);


--
-- Name: work_order_pause_reasons update_work_order_pause_reasons_timestamp; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_work_order_pause_reasons_timestamp BEFORE UPDATE ON public.work_order_pause_reasons FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: andon_escalation_logs andon_escalation_logs_ticket_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.andon_escalation_logs
    ADD CONSTRAINT andon_escalation_logs_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES public.andon_tickets(id) ON DELETE CASCADE;


--
-- Name: andon_tickets andon_tickets_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.andon_tickets
    ADD CONSTRAINT andon_tickets_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.andon_categories(id);


--
-- Name: andon_tickets andon_tickets_work_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.andon_tickets
    ADD CONSTRAINT andon_tickets_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES public.work_orders(id);


--
-- Name: aps_schedule_tasks aps_schedule_tasks_schedule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aps_schedule_tasks
    ADD CONSTRAINT aps_schedule_tasks_schedule_id_fkey FOREIGN KEY (schedule_id) REFERENCES public.aps_schedules(id);


--
-- Name: attendance attendance_operator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attendance
    ADD CONSTRAINT attendance_operator_id_fkey FOREIGN KEY (operator_id) REFERENCES public.operators(id);


--
-- Name: chat_events chat_events_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_events
    ADD CONSTRAINT chat_events_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE;


--
-- Name: chat_goal_metrics chat_goal_metrics_goal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_goal_metrics
    ADD CONSTRAINT chat_goal_metrics_goal_id_fkey FOREIGN KEY (goal_id) REFERENCES public.chat_goals(id) ON DELETE CASCADE;


--
-- Name: chat_goals chat_goals_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_goals
    ADD CONSTRAINT chat_goals_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE;


--
-- Name: chat_message_attachments chat_message_attachments_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_message_attachments
    ADD CONSTRAINT chat_message_attachments_file_id_fkey FOREIGN KEY (file_id) REFERENCES public.files(id) ON DELETE CASCADE;


--
-- Name: chat_message_attachments chat_message_attachments_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_message_attachments
    ADD CONSTRAINT chat_message_attachments_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.chat_messages(id) ON DELETE CASCADE;


--
-- Name: chat_message_attachments chat_message_attachments_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_message_attachments
    ADD CONSTRAINT chat_message_attachments_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE;


--
-- Name: chat_messages chat_messages_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE;


--
-- Name: chat_session_events chat_session_events_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_session_events
    ADD CONSTRAINT chat_session_events_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id);


--
-- Name: chat_telemetry chat_telemetry_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_telemetry
    ADD CONSTRAINT chat_telemetry_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE SET NULL;


--
-- Name: cycle_count_items cycle_count_items_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycle_count_items
    ADD CONSTRAINT cycle_count_items_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.cycle_count_tasks(id);


--
-- Name: defect_records defect_records_equipment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.defect_records
    ADD CONSTRAINT defect_records_equipment_id_fkey FOREIGN KEY (equipment_id) REFERENCES public.equipment(id);


--
-- Name: defect_records defect_records_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.defect_records
    ADD CONSTRAINT defect_records_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: defect_records defect_records_production_report_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.defect_records
    ADD CONSTRAINT defect_records_production_report_id_fkey FOREIGN KEY (production_report_id) REFERENCES public.production_reports(id);


--
-- Name: defect_records defect_records_work_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.defect_records
    ADD CONSTRAINT defect_records_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES public.work_orders(id);


--
-- Name: equipment_downtime equipment_downtime_equipment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equipment_downtime
    ADD CONSTRAINT equipment_downtime_equipment_id_fkey FOREIGN KEY (equipment_id) REFERENCES public.equipment(id);


--
-- Name: quality_red_tag_attachments fk_red_tag_attachment; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_red_tag_attachments
    ADD CONSTRAINT fk_red_tag_attachment FOREIGN KEY (red_tag_id) REFERENCES public.quality_red_tag(id) ON DELETE CASCADE;


--
-- Name: quality_red_tag fk_red_tag_defect; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_red_tag
    ADD CONSTRAINT fk_red_tag_defect FOREIGN KEY (defect_id) REFERENCES public.defect_records(id) ON DELETE CASCADE;


--
-- Name: quality_red_tag_attachments fk_red_tag_file; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_red_tag_attachments
    ADD CONSTRAINT fk_red_tag_file FOREIGN KEY (file_id) REFERENCES public.files(id) ON DELETE CASCADE;


--
-- Name: quality_red_tag fk_red_tag_station; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_red_tag
    ADD CONSTRAINT fk_red_tag_station FOREIGN KEY (station_id) REFERENCES public.stations(id) ON DELETE SET NULL;


--
-- Name: quality_red_tag fk_red_tag_workorder; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_red_tag
    ADD CONSTRAINT fk_red_tag_workorder FOREIGN KEY (work_order_id) REFERENCES public.work_orders(id) ON DELETE SET NULL;


--
-- Name: supplier_materials fk_supplier_material_supplier; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplier_materials
    ADD CONSTRAINT fk_supplier_material_supplier FOREIGN KEY (supplier_id) REFERENCES public.suppliers(id) ON DELETE CASCADE;


--
-- Name: work_orders fk_wo_parent; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT fk_wo_parent FOREIGN KEY (parent_work_order_id) REFERENCES public.work_orders(id);


--
-- Name: goods_receipts goods_receipts_po_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.goods_receipts
    ADD CONSTRAINT goods_receipts_po_id_fkey FOREIGN KEY (po_id) REFERENCES public.purchase_orders(id);


--
-- Name: hr_employee_skills hr_employee_skills_hr_employee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hr_employee_skills
    ADD CONSTRAINT hr_employee_skills_hr_employee_id_fkey FOREIGN KEY (hr_employee_id) REFERENCES public.hr_employees(id) ON DELETE CASCADE;


--
-- Name: hr_employee_skills hr_employee_skills_skill_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hr_employee_skills
    ADD CONSTRAINT hr_employee_skills_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(id);


--
-- Name: hr_employees hr_employees_factory_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hr_employees
    ADD CONSTRAINT hr_employees_factory_id_fkey FOREIGN KEY (factory_id) REFERENCES public.factories(id);


--
-- Name: im_group_members im_group_members_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.im_group_members
    ADD CONSTRAINT im_group_members_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.im_groups(id);


--
-- Name: im_messages im_messages_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.im_messages
    ADD CONSTRAINT im_messages_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.im_groups(id);


--
-- Name: inspection_items inspection_items_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_items
    ADD CONSTRAINT inspection_items_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.inspection_tasks(id);


--
-- Name: inventory_count_items inventory_count_items_count_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_count_items
    ADD CONSTRAINT inventory_count_items_count_id_fkey FOREIGN KEY (count_id) REFERENCES public.inventory_counts(id);


--
-- Name: inventory_count_items inventory_count_items_inventory_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_count_items
    ADD CONSTRAINT inventory_count_items_inventory_id_fkey FOREIGN KEY (inventory_id) REFERENCES public.inventory(id);


--
-- Name: inventory_counts inventory_counts_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_counts
    ADD CONSTRAINT inventory_counts_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouses(id);


--
-- Name: inventory_transactions inventory_transactions_inventory_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_transactions
    ADD CONSTRAINT inventory_transactions_inventory_id_fkey FOREIGN KEY (inventory_id) REFERENCES public.inventory(id);


--
-- Name: item_traceability item_traceability_equipment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_traceability
    ADD CONSTRAINT item_traceability_equipment_id_fkey FOREIGN KEY (equipment_id) REFERENCES public.equipment(id);


--
-- Name: item_traceability item_traceability_next_item_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_traceability
    ADD CONSTRAINT item_traceability_next_item_code_fkey FOREIGN KEY (next_item_code) REFERENCES public.item_traceability(item_code);


--
-- Name: item_traceability item_traceability_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_traceability
    ADD CONSTRAINT item_traceability_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: item_traceability item_traceability_work_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_traceability
    ADD CONSTRAINT item_traceability_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES public.work_orders(id);


--
-- Name: job_card_time_logs job_card_time_logs_work_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_card_time_logs
    ADD CONSTRAINT job_card_time_logs_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES public.work_orders(id);


--
-- Name: job_dispatches job_dispatches_operator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_dispatches
    ADD CONSTRAINT job_dispatches_operator_id_fkey FOREIGN KEY (operator_id) REFERENCES public.operators(id);


--
-- Name: job_dispatches job_dispatches_station_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_dispatches
    ADD CONSTRAINT job_dispatches_station_id_fkey FOREIGN KEY (station_id) REFERENCES public.stations(id);


--
-- Name: job_dispatches job_dispatches_work_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_dispatches
    ADD CONSTRAINT job_dispatches_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES public.work_orders(id);


--
-- Name: maintenance_checklist maintenance_checklist_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_checklist
    ADD CONSTRAINT maintenance_checklist_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.maintenance_tasks(id);


--
-- Name: maintenance_orders maintenance_orders_equipment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_orders
    ADD CONSTRAINT maintenance_orders_equipment_id_fkey FOREIGN KEY (equipment_id) REFERENCES public.equipment(id);


--
-- Name: maintenance_plans maintenance_plans_equipment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_plans
    ADD CONSTRAINT maintenance_plans_equipment_id_fkey FOREIGN KEY (equipment_id) REFERENCES public.equipment(id);


--
-- Name: operators operators_dept_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operators
    ADD CONSTRAINT operators_dept_id_fkey FOREIGN KEY (dept_id) REFERENCES public.departments(id);


--
-- Name: operators operators_team_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operators
    ADD CONSTRAINT operators_team_id_fkey FOREIGN KEY (team_id) REFERENCES public.teams(id);


--
-- Name: order_decomposition_logs order_decomposition_logs_sales_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_decomposition_logs
    ADD CONSTRAINT order_decomposition_logs_sales_order_id_fkey FOREIGN KEY (sales_order_id) REFERENCES public.sales_orders(id);


--
-- Name: pick_list_items pick_list_items_pick_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pick_list_items
    ADD CONSTRAINT pick_list_items_pick_list_id_fkey FOREIGN KEY (pick_list_id) REFERENCES public.pick_lists(id);


--
-- Name: pick_lists pick_lists_work_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pick_lists
    ADD CONSTRAINT pick_lists_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES public.work_orders(id);


--
-- Name: pull_replenishment_tasks pull_replenishment_tasks_source_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pull_replenishment_tasks
    ADD CONSTRAINT pull_replenishment_tasks_source_warehouse_id_fkey FOREIGN KEY (source_warehouse_id) REFERENCES public.warehouses(id);


--
-- Name: pull_replenishment_tasks pull_replenishment_tasks_target_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pull_replenishment_tasks
    ADD CONSTRAINT pull_replenishment_tasks_target_location_id_fkey FOREIGN KEY (target_location_id) REFERENCES public.locations(id);


--
-- Name: pull_replenishment_tasks pull_replenishment_tasks_threshold_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pull_replenishment_tasks
    ADD CONSTRAINT pull_replenishment_tasks_threshold_id_fkey FOREIGN KEY (threshold_id) REFERENCES public.replenishment_thresholds(id);


--
-- Name: pull_replenishment_tasks pull_replenishment_tasks_work_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pull_replenishment_tasks
    ADD CONSTRAINT pull_replenishment_tasks_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES public.work_orders(id);


--
-- Name: purchase_orders purchase_orders_pr_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_pr_id_fkey FOREIGN KEY (pr_id) REFERENCES public.purchase_requisitions(id);


--
-- Name: purchase_orders purchase_orders_supplier_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_supplier_id_fkey FOREIGN KEY (supplier_id) REFERENCES public.suppliers(id);


--
-- Name: qms_8d_reports qms_8d_reports_defect_record_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qms_8d_reports
    ADD CONSTRAINT qms_8d_reports_defect_record_id_fkey FOREIGN KEY (defect_record_id) REFERENCES public.defect_records(id);


--
-- Name: qms_inspection_items qms_inspection_items_inspection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qms_inspection_items
    ADD CONSTRAINT qms_inspection_items_inspection_id_fkey FOREIGN KEY (inspection_id) REFERENCES public.quality_inspections(id);


--
-- Name: quality_goal_reviews quality_goal_reviews_goal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_goal_reviews
    ADD CONSTRAINT quality_goal_reviews_goal_id_fkey FOREIGN KEY (goal_id) REFERENCES public.quality_goals(id);


--
-- Name: quality_inspections quality_inspections_work_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_inspections
    ADD CONSTRAINT quality_inspections_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES public.work_orders(id);


--
-- Name: quotations quotations_rfq_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotations
    ADD CONSTRAINT quotations_rfq_id_fkey FOREIGN KEY (rfq_id) REFERENCES public.rfqs(id);


--
-- Name: reconciliation_logs reconciliation_logs_work_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reconciliation_logs
    ADD CONSTRAINT reconciliation_logs_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES public.work_orders(id);


--
-- Name: replenishment_thresholds replenishment_thresholds_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.replenishment_thresholds
    ADD CONSTRAINT replenishment_thresholds_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id);


--
-- Name: replenishment_thresholds replenishment_thresholds_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.replenishment_thresholds
    ADD CONSTRAINT replenishment_thresholds_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouses(id);


--
-- Name: routing_steps routing_steps_routing_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_steps
    ADD CONSTRAINT routing_steps_routing_id_fkey FOREIGN KEY (routing_id) REFERENCES public.routings(id);


--
-- Name: routing_template_steps routing_template_steps_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_template_steps
    ADD CONSTRAINT routing_template_steps_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.routing_templates(id);


--
-- Name: rush_order_approval_logs rush_order_approval_logs_approval_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rush_order_approval_logs
    ADD CONSTRAINT rush_order_approval_logs_approval_id_fkey FOREIGN KEY (approval_id) REFERENCES public.rush_order_approvals(id);


--
-- Name: shipment_items shipment_items_shipment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shipment_items
    ADD CONSTRAINT shipment_items_shipment_id_fkey FOREIGN KEY (shipment_id) REFERENCES public.shipments(id) ON DELETE CASCADE;


--
-- Name: supplier_prices supplier_prices_supplier_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplier_prices
    ADD CONSTRAINT supplier_prices_supplier_id_fkey FOREIGN KEY (supplier_id) REFERENCES public.suppliers(id);


--
-- Name: teams teams_dept_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT teams_dept_id_fkey FOREIGN KEY (dept_id) REFERENCES public.departments(id);


--
-- Name: trainer_defects trainer_defects_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trainer_defects
    ADD CONSTRAINT trainer_defects_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.training_sessions(id) ON DELETE CASCADE;


--
-- Name: training_sessions training_sessions_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_sessions
    ADD CONSTRAINT training_sessions_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.training_scenarios(id);


--
-- Name: wms_inventory_pool_members wms_inventory_pool_members_pool_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_inventory_pool_members
    ADD CONSTRAINT wms_inventory_pool_members_pool_id_fkey FOREIGN KEY (pool_id) REFERENCES public.wms_inventory_pools(id);


--
-- Name: wms_rfid_count_items wms_rfid_count_items_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wms_rfid_count_items
    ADD CONSTRAINT wms_rfid_count_items_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.wms_rfid_count_sessions(id);


--
-- Name: wo_status_logs wo_status_logs_work_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wo_status_logs
    ADD CONSTRAINT wo_status_logs_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES public.work_orders(id);


--
-- Name: work_orders work_orders_assigned_station_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_assigned_station_id_fkey FOREIGN KEY (assigned_station_id) REFERENCES public.stations(id);


--
-- Name: work_orders work_orders_pause_reason_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_pause_reason_id_fkey FOREIGN KEY (pause_reason_id) REFERENCES public.work_order_pause_reasons(id);


--
-- PostgreSQL database dump complete
--

\unrestrict wMTZ2rr9CKGKb9LClP0mhmgMF7vjctVrTyseYtuKu8SFfI1J2fSkZVVoWt7UNY9


-- ---------------------------------------------------------------------------
-- 台账种子：87 条已应用迁移。**不要删**，理由见文件头。
-- ---------------------------------------------------------------------------
INSERT INTO public.enghub_schema_migrations (migration_name, checksum, applied_at) VALUES
  ('042_runtime_schema_alignment.sql', '7b57212ae8cae289fa40e3dcfa236f94949c9f46e2d5c1dd90631f7078dd3876', '2026-08-01 11:56:32.415458'::timestamp),
  ('043_runtime_schema_alignment_followup.sql', 'da788f48965fa268f92fc2f4b68e58b3c1b580fc63074148010ce6f7297b86a6', '2026-08-01 11:56:32.415458'::timestamp),
  ('044_detail_endpoint_alignment.sql', '9813a9c6059602cc532baab35078f1a2406d9dfecea343a249b868f381b590c0', '2026-08-01 11:56:32.415458'::timestamp),
  ('045_production_report_fields_extension.sql', '2552f04c1a1b35d22b20afceccedb3f97ebb950c529edae82b844c95b2346a6d', '2026-08-01 11:56:32.415458'::timestamp),
  ('046_production_report_constraints.sql', 'eb59be7672bdb75fbefc896f1cb8d85019899743a2428fc6ef9f8ef7b400f717', '2026-08-01 11:56:32.415458'::timestamp),
  ('046_work_order_inventory_reservation_fields.sql', '7d20faa30265b77da5733021052257bc8e09bc5eedf8dee2506638bef8888b99', '2026-08-01 11:56:32.415458'::timestamp),
  ('047_aps_request_queue.sql', 'aa9bdde8eb776d8a783906649a311488ee4a0ae83e65c2ce2773145e6e8e4044', '2026-08-01 11:56:32.415458'::timestamp),
  ('047_purchase_requisition_table.sql', '79b4be209393c1af85ff1457b602dd17c66196f5f8c7d6a2946a3e3a712642a1', '2026-08-01 11:56:32.415458'::timestamp),
  ('048_work_order_pause_reason_table.sql', '13c33d09df3a26d58182245e535e9debaaf743f15053490e604d6937c4c8a17d', '2026-08-01 11:56:32.415458'::timestamp),
  ('049_supplier_table.sql', '110d7ac9202afbe453f1a23ffb68435494e50f67df0b5b7cf9bea03985a452d9', '2026-08-01 11:56:32.415458'::timestamp),
  ('050_workflow_rules_tables.sql', '500ccb60add66d0cb0cbd7f906fba6d5bd815b5b60063342b0785cd0ff134c40', '2026-08-01 11:56:32.415458'::timestamp),
  ('050_workflow_state_rules.sql', '4c476f69476b63c21b1e30288bfa055a21834bb2a4b3e9982744a9f83868f029', '2026-08-01 11:56:32.415458'::timestamp),
  ('051_workflow_action_gates.sql', '4c91afc73623fc79378ffde00413b144b7a261ad375af3e14d29dd7cbef3cb12', '2026-08-01 11:56:32.415458'::timestamp),
  ('052_workflow_action_gate_table.sql', 'b7fd56993b8dc69ba19a205b41008a6cd2106b13f19b86e407bc79ca9b6db071', '2026-08-01 11:56:32.415458'::timestamp),
  ('053_supplier_material_junction.sql', 'ad5315671696c7b0ad12a0cf83308b383119838a9948819b80d80fa784adf576', '2026-08-01 11:56:32.415458'::timestamp),
  ('054_inventory_safety_stock.sql', '2f322092d6ca29fb24386486bb48bee428f2e1f1a4fd3318f12f88580c91f19e', '2026-08-01 11:56:32.415458'::timestamp),
  ('055_business_completeness_fields.sql', 'c665f0663fa77aaa038aae2ad5d1f74dedbff45841ea06927e9d6b0fae82a691', '2026-08-01 11:56:32.415458'::timestamp),
  ('056_runtime_model_alignment.sql', 'bbc22248c7ce2a817f2264110290186d9fbb69bbe9abec203eadf9d7f84f0719', '2026-08-01 11:56:32.415458'::timestamp),
  ('057_fix_missing_columns_tables.sql', 'e3e32c675e75db6dd84013cfabb89aa417a0afb600cfafd46ccaefed16c23083', '2026-08-01 11:56:32.762952'::timestamp),
  ('057_notification_audit_fields.sql', '617fe61dd5ab2454d489802dd1c64b6992248943752284d97e3f27f90ab7af8f', '2026-08-01 11:56:32.766692'::timestamp),
  ('058_chat_quick_commands.sql', 'a08faaa959b9b6beb724ecc3f0baa4aa16f4d6d97499b8105125422e3463cd46', '2026-08-01 11:56:32.775096'::timestamp),
  ('058_user_password_reset_fields.sql', 'a7915824779b84c4c752c443887f463d42f70ac26deb9c2924c029d44c81ee52', '2026-08-01 12:11:27.422824'::timestamp),
  ('059_followup_tasks.sql', '9bfd678eb839441c31a44580e4e15ffabda595fc391a9e0b86e4e4f31ae6e2eb', '2026-08-01 11:56:32.793708'::timestamp),
  ('060_task_center_inbox.sql', 'fdd6512bc9378f161571bf4e1596efcbb402a56309f35006831758c2544f33a9', '2026-08-01 11:56:32.804892'::timestamp),
  ('061_equipment_responsible_engineer.sql', '4663cc5c8f8f8eb4c0f75ce68bad6746080c1b5f269b070255b6dfc762d938df', '2026-08-01 13:21:35.446429'::timestamp),
  ('062_commander_plans.sql', '49772172222aea8ac7feb0045b92498f3f07ee6af17ff125fbfd428f79b0b4bb', '2026-08-13 08:50:42.811655'::timestamp),
  ('062_wms_material_volume.sql', '6f2cd18f947a4a4035fa061ae2b8da909c8db50a2434faa8cc03df91175c2ad6', '2026-08-02 15:31:03.322376'::timestamp),
  ('063_quality_red_tag.sql', '525e2905e85acad780393285d55edb94318456982049492ad96c84ffa0f882b8', '2026-08-13 08:50:42.811655'::timestamp),
  ('063_wms_full_enhancement.sql', '518e32841f51cfd77cc26ec3210717fbd443d1f3e8635b34f9f594d2f25023b3', '2026-08-02 16:21:42.429834'::timestamp),
  ('064_aps_holiday_calendars.sql', 'a395bc2bfa7be01a149f1fe3b32d0e1a04dc803281e1173f919c904cc5b9d5fa', '2026-08-13 01:33:31.506185'::timestamp),
  ('064_bom_factory_scope.sql', 'c7ce3e7eeb07e2d9ee66e648fbb44144da8cee2f3f56b3e49518225786fa589e', '2026-08-03 00:30:30.723098'::timestamp),
  ('065_position_training.sql', 'c90850965bc35f2483243e62eae0d689a6b3692a639cec284783c85f84c12de8', '2026-08-13 01:33:31.506185'::timestamp),
  ('065_wms_inventory_order_links.sql', '5312e73803ba24bc11f74c9c9524a14b68af4ab2071d0c10ad37ce55d4ff25ee', '2026-08-08 09:23:52.230454'::timestamp),
  ('066_ai_memory_candidates.sql', 'ebf1a3f2241b91971471b9aa5a3523ab5108f76b7980afa6a1d9886aea8857b2', '2026-08-08 09:23:52.230454'::timestamp),
  ('066_aps_control_closure.sql', '5e506a628aa7cd42819de6f43da7a1c94a610d0d2c70a6d10ea47b3f93630843', '2026-08-13 08:50:42.811655'::timestamp),
  ('067_capa_workflow_persistence.sql', '002f4bd81f34b87290c597176ecac2deca5443883d4fe631ed8258b47c0d0bc9', '2026-08-08 09:23:52.230454'::timestamp),
  ('067_pmc_workbench_bootstrap.sql', '68cb339c889a53c0f9cc680dbe72b1c478c24fd2f035de9814955ca6657ec082', '2026-08-13 01:33:31.506185'::timestamp),
  ('068_ai_experience_compounding.sql', '058d1a6693e5297c442f6af0e5b263d8fa7bfdc5536e017b7f1cd2b1c631ab65', '2026-08-08 09:23:52.230454'::timestamp),
  ('068_rush_order_approvals.sql', 'ffed78bf21334af9dc7ae668cce2153fd57f1bd7328808eeed1db6e954f030a7', '2026-08-13 08:50:42.811655'::timestamp),
  ('069_ai_action_approvals.sql', '2c7d52a2c76a6a5ec206a8d91a548fcd3d5926c976849e0edbcd3f35a2ffe999', '2026-08-08 09:23:52.230454'::timestamp),
  ('070_chatbot_role_trainer.sql', '9bcf4702cf68ee6eb2fc451c1c61494849948e0294d783eb3f18f5ddbee64748', '2026-08-08 09:23:52.230454'::timestamp),
  ('071_internal_meetings.sql', 'e0742b97e52df4a8605bb9dcbc0de7a658c51e6921a6a7bd271edb46face8f8d', '2026-08-08 12:12:25.301353'::timestamp),
  ('072_virtual_factory_operational_stream.sql', 'a99fa8c1de47a49d67c767ab0ca3ee907c1a81e557e8155505518f2817f0c47d', '2026-08-08 12:35:53.167971'::timestamp),
  ('073_role_simulation_and_defects.sql', '0a4b73f9e6363869a9b9400136096f2f8b4408c833dd6c968d99ec67db9e22bb', '2026-08-08 13:57:31.817959'::timestamp),
  ('074_virtual_factory_quality_profiles.sql', '7bac1d5783dbc6557be8d6ad991fa2ae7a65692d45516977000cb1db0b34a1e1', '2026-08-08 14:11:03.932116'::timestamp),
  ('075_pmc_training_pack.sql', 'c7e1f77247baf5de19a735a10a7c49458e8497c0d0da5f01e8f11f85c130dbde', '2026-08-08 15:16:14.720809'::timestamp),
  ('076_enterprise_knowledge_documents.sql', '23dda7d020ee3660ce6cd9d9b39c9cd98c43828aa2c72f189d69b321830269bd', '2026-08-08 15:53:51.584466'::timestamp),
  ('077_virtual_factory_bom.sql', 'a39835c8afb0d8cd909010c67e93a27d48bcf78b78f6ffe9815e0964c25f34d3', '2026-08-10 01:49:43.895185'::timestamp),
  ('078_order_review.sql', '8948238eaafc60592575070a388e76129f7aac21120b82383dfe0477d7b75fc8', '2026-08-10 01:21:02.255799'::timestamp),
  ('079_atp_wheel_routing.sql', '791d470fe7a134014d8b284a6d7a3b8906d7615ed4292fb1adb0f204d2e08921', '2026-08-10 01:49:43.895185'::timestamp),
  ('080_treadmill_production_flow.sql', '97f9e793ecf5a7a5e59704fa87ba9bbe3cf34650c6c81029b5e4ce9a60b95f06', '2026-08-10 02:28:05.464285'::timestamp),
  ('081_treadmill_crp_alignment.sql', 'd767346188e8503923ca55ba5fd5ff6fc05e50a79da3af15c36779889d4b835a', '2026-08-10 02:31:31.294465'::timestamp),
  ('082_chat_engflow_persistence.sql', 'fc1f1e454b9121690b08d8e46e1373348383a694781b798890d73a1eb32e3dd6', '2026-08-13 08:50:42.811655'::timestamp),
  ('083_agent_events_persistence_alignment.sql', '042461269c4fe690c02f2daf2eadfcfd91accdaaf0a18990c0d152fbfcdbc6cb', '2026-08-13 08:50:42.811655'::timestamp),
  ('084_agent_checkpoints.sql', '9800ce2b5114246e8aea432ad4d746fcec1459377962d5cbdce60481644e6108', '2026-08-13 08:50:42.811655'::timestamp),
  ('085_pmc_control_tower_sources.sql', '635ed96fc4bbe1a1938b07590e307d29730c8229379654f45e527acb8bda642a', '2026-08-13 08:50:42.811655'::timestamp),
  ('086_pmc_data_readiness_and_capacity.sql', '99e0ceb14b4b75df479001efdd772b1040e72c7caf1dbab7e22353cd8b0f5aa2', '2026-08-13 08:50:42.811655'::timestamp),
  ('087_online_workbooks.sql', '07b33c8ace6daa5f30cb40c5c5c870f6a5fc4e8491162f9e474a0c954e344571', '2026-08-13 08:50:42.811655'::timestamp),
  ('088_aps_schedule_schema_alignment.sql', 'ac39eec42b9ce33a457d5ab31a3b8d531b9638e4e4e73d5ec9936b466557b4da', '2026-08-13 08:50:42.811655'::timestamp),
  ('089_followup_tasks_schema_alignment.sql', 'e212836243a31b62501cf4ec848260111599d7c72c2945856cbeb5362ad66682', '2026-08-13 08:50:42.811655'::timestamp),
  ('090_rush_order_schema_alignment.sql', '13ad01fda4056d791171d6b79c7560ed2c487a78c7e79dca029bc6820aa89c3a', '2026-08-13 08:50:42.811655'::timestamp),
  ('091_commander_plans_schema_alignment.sql', '8fb8e16c7f41166c68a54f742f34703cd2522d2589e8f43b5a8218f5f10bbce4', '2026-08-13 08:50:42.811655'::timestamp),
  ('092_operational_coverage_seed.sql', '918a8e57c436eb73483163cd843736334812c99d00d3b5ef87afe3a7c5960b0f', '2026-08-13 09:14:46.955225'::timestamp),
  ('093_chat_message_attachments.sql', 'ff8c8286ddd71524b2b5647388daa63a11a5d2da27016d898df7663fcd3611d9', '2026-08-13 13:58:32.824593'::timestamp),
  ('094_chat_harness_events.sql', '23c01e6ef8dd5934b6864e0424da9dda93f644f33099e0d2c166da6b0a0b0cdb', '2026-08-22 01:12:00.903333'::timestamp),
  ('094_position_training_expand.sql', 'e03274800a20ef31c82137dd5735f5b916395f934820378abec4a84fae0c1a25', '2026-08-14 04:04:11.593249'::timestamp),
  ('095_chat_goals.sql', '45896199e94f875521dd197a833b900ca6333af479460e30217bfa26cfd575bd', '2026-08-22 03:44:06.472043'::timestamp),
  ('095_pmc_training_advanced.sql', 'c55969671d9ba4de00b69e027c3569b3b9d09e5f470c30a56ee2a47e9db15a04', '2026-08-14 04:04:11.593249'::timestamp),
  ('096_chat_goal_metrics.sql', 'f28f0b2b53c935f1337c1fae3b50692470de040e026b9b067ee618494195062e', '2026-08-22 04:03:14.122689'::timestamp),
  ('096_pmc_training_question_types.sql', 'f68726e5581991d358860939b397ca33614a0e0e6f98fb00942ca5bd9b0521cf', '2026-08-14 04:12:42.366443'::timestamp),
  ('097_chat_memories.sql', '47ee9f0d65dfcd4b4bce2dbfd5d6e756422163e0d8a60252f9efb4cfcc1b41cd', '2026-08-14 09:18:34.706957'::timestamp),
  ('097_engine_heartbeats.sql', 'b66c9d61598e8b63b3084c9ca1f3300a27fa30d1503567aa68d459066a239515', '2026-10-04 12:59:58.262059'::timestamp),
  ('097_wms_order_link_columns.sql', 'ff279dcf9e2247d3fc90ef97ce60dcd2452c210168b1d8f3ea359a19b7e4518f', '2026-10-04 02:05:07.567575'::timestamp),
  ('098_bom_mirror_order_columns.sql', '2d06537d7a0b2c416194c819096dfaf66f9aca79ff5ac178f9c6ba467c36ec2e', '2026-10-04 14:11:01.283614'::timestamp),
  ('098_chat_session_events.sql', '9f6fe35f8e816bbe1dbcb674777928b56bfe183b5f5f2a9ab8a05646211a193b', '2026-08-14 10:00:40.872852'::timestamp),
  ('098_wms_location_manager_columns.sql', '94668009d7d54a040d0bf757f10eb2dc30bd8f5fe2723d913029f4fb8c957bc8', '2026-10-04 02:05:07.567575'::timestamp),
  ('099_commander_decision_log.sql', '4fa8ba3cbe33b7bd1b920b6a7a4bd68a23b0c172b15646e13b7f9d73b975b514', '2026-10-04 06:11:05.994247'::timestamp),
  ('100_mrp_wom_level_structure.sql', '83c382a5bc9b76df8f00b2e8bce9faec35f94815f519e245ae396f903f3ed3b4', '2026-10-04 14:46:09.321931'::timestamp),
  ('101_aps_input_fingerprint.sql', '82939b68b4b353bd39a91f0f1f95939c516765bc3a8c6ce0aef523399afa5eaa', '2026-10-05 12:10:04.346471'::timestamp),
  ('102_wom_numeric_quantities.sql', 'c5e8c7ecda39e1dc824ab0d42c92f6fbfc6938f84cd8bdbe38eba88753c0e948', '2026-10-05 23:25:00.640698'::timestamp),
  ('103_cost_parameters.sql', 'a59bb63aeebe5b19592f1b8c0d7e72a0a3715f75267d06fc765aa6e0b9ec81e6', '2026-10-06 02:16:03.304359'::timestamp),
  ('104_line_profiles.sql', 'dd8ec081cd54cd5939d267cdac2bb0d36b6cc165a6e2a30f90d0e820869cbb68', '2026-10-06 03:35:12.316427'::timestamp),
  ('105_line_groups.sql', 'a8908e6fbe337829deefad933d35cdb8f0d70ab55c4ca9496aaa89d6b52959e4', '2026-10-06 03:35:12.316427'::timestamp),
  ('106_task_duration_basis.sql', '3b84c28af1632abb53e33f55b0024741cd88d1d2ee6de8fa30be7bf887885da1', '2026-10-06 04:14:30.678426'::timestamp),
  ('107_simulation_scorecards.sql', '95293932d3f3082b410ecd11c5d51054f5eb33a5402d339704d75cd58e94e64c', '2026-10-06 09:24:40.411352'::timestamp),
  ('108_engine_error_ring.sql', '537ffa9cfb7c0f7d27cc1938ef855688a30fadff7c25414088b5f82cd83d6227', '2026-10-06 14:04:18.370769'::timestamp),
  ('109_engine_crash_window.sql', 'e3ed5ecd9b1dc38aeb186a8a0b1cc87c522b933b0c219034a6abae46fc1e9f3d', '2026-10-06 14:56:52.14892'::timestamp)
ON CONFLICT (migration_name) DO NOTHING;
