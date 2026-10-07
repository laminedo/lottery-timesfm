-- Lottery analytics schema. Plain PostgreSQL: runs on the embedded dev server, Supabase and Neon alike.

create table games (
    game_key        text primary key,
    name            text not null,
    pick_count      smallint not null,
    pool_size       smallint not null,
    bonus_pool_size smallint,
    bonus_name      text,
    updated_at      timestamptz not null default now()
);

-- One row per official drawing. Only draws under each game's current main matrix are stored.
create table draws (
    draw_id         bigint generated always as identity primary key,
    game_key        text not null references games (game_key),
    draw_date       date not null,
    primary_numbers integer[] not null,          -- sorted ascending
    bonus_number    integer,
    multiplier      integer,
    jackpot_usd     bigint,                      -- advertised top prize for this draw, when known
    source          text not null,
    ingested_at     timestamptz not null default now(),
    unique (game_key, draw_date),
    check (cardinality(primary_numbers) between 1 and 10)
);
create index draws_game_date_idx on draws (game_key, draw_date desc);

-- Advertised jackpot for an upcoming draw, captured before it happens.
create table jackpot_estimates (
    game_key       text not null references games (game_key),
    draw_date      date not null,
    jackpot_usd    bigint not null,
    cash_value_usd bigint,
    source         text not null,
    fetched_at     timestamptz not null default now(),
    primary key (game_key, draw_date)
);

-- Cached model output for "the draw after as_of_draw_id". pipeline_key identifies backend and settings.
create table model_outputs (
    output_id     bigint generated always as identity primary key,
    game_key      text not null references games (game_key),
    as_of_draw_id bigint not null references draws (draw_id) on delete cascade,
    pipeline_key  text not null,
    payload       jsonb not null,
    created_at    timestamptz not null default now(),
    unique (game_key, as_of_draw_id, pipeline_key)
);

-- A "Generate" click: the settings used and the draw the lines were made for.
create table forecasts (
    forecast_id      bigint generated always as identity primary key,
    game_key         text not null references games (game_key),
    created_at       timestamptz not null default now(),
    target_draw_date date not null,
    as_of_draw_id    bigint references draws (draw_id) on delete set null,
    strategy         text not null,
    backend          text not null,
    params           jsonb not null
);
create index forecasts_game_idx on forecasts (game_key, created_at desc);

-- The candidate lines of a forecast. Scored once the target draw has been ingested.
create table forecast_lines (
    line_id         bigint generated always as identity primary key,
    forecast_id     bigint not null references forecasts (forecast_id) on delete cascade,
    line_no         smallint not null,
    primary_numbers integer[] not null,
    bonus_number    integer,
    draw_id         bigint references draws (draw_id) on delete set null,
    main_matches    smallint,
    bonus_match     boolean,
    evaluated_at    timestamptz
);
create index forecast_lines_forecast_idx on forecast_lines (forecast_id);

-- Walk-forward backtests: parameters, progress while running, and the final result.
create table backtest_runs (
    run_id      bigint generated always as identity primary key,
    game_key    text not null references games (game_key),
    created_at  timestamptz not null default now(),
    finished_at timestamptz,
    status      text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed')),
    params      jsonb not null,
    progress    real not null default 0,
    message     text,
    result      jsonb,
    error       text
);
create index backtest_runs_game_idx on backtest_runs (game_key, created_at desc);

-- Supabase exposes the public schema through its REST API. With row level security on and no
-- policies, only the API server's own connection can read or write these tables.
alter table games enable row level security;
alter table draws enable row level security;
alter table jackpot_estimates enable row level security;
alter table model_outputs enable row level security;
alter table forecasts enable row level security;
alter table forecast_lines enable row level security;
alter table backtest_runs enable row level security;
