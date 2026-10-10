-- =====================================================================
--  schema_update.sql  —  Telegram Shop Bot (fa/en)
--  Run the WHOLE file once in Supabase -> SQL Editor.  Safe to re-run.
--  * creates every table if it is missing (so it also works on an empty DB)
--  * adds every column the bot needs if it is missing
--  * never drops or rewrites your data
--  The bot must use the Supabase **service_role** key (RLS is enabled below).
-- =====================================================================

-- ---------------------------------------------------------------- 1) base tables
create table if not exists public.users (
  id uuid primary key default gen_random_uuid(),
  telegram_id bigint not null,
  created_at timestamptz not null default now()
);
create table if not exists public.settings (
  key text primary key,
  value text
);
create table if not exists public.categories (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.shops (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.products (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.cart_items (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.orders (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.order_items (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.coupons (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.deals (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.product_reviews (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.product_reports (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.plans (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.support_messages (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create table if not exists public.payment_receipts (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- 2) NEW tables
-- saved delivery address (one per customer, reused at the next checkout)
create table if not exists public.addresses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  full_name text,
  phone text,
  address text,
  postal_code text,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);
-- unfinished forms (address, product wizard...) survive a Render restart
create table if not exists public.bot_states (
  chat_id bigint primary key,
  kind text,
  data jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
-- every Telegram Stars charge: stops a duplicated webhook from paying/delivering twice
create table if not exists public.payments_ledger (
  charge_id text primary key,
  kind text,
  ref text,
  user_id uuid,
  telegram_id bigint,
  amount integer,
  currency text,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- 3) columns
-- users
alter table public.users add column if not exists username text;
alter table public.users add column if not exists first_name text;
alter table public.users add column if not exists language text not null default 'fa';
alter table public.users add column if not exists language_set boolean not null default false;
alter table public.users add column if not exists wallet_balance numeric not null default 0;
alter table public.users add column if not exists points integer not null default 0;
alter table public.users add column if not exists role text not null default 'user';
alter table public.users add column if not exists trial_used boolean not null default false;
alter table public.users add column if not exists support_username text;

-- categories
alter table public.categories add column if not exists parent_id uuid;
alter table public.categories add column if not exists name_fa text;
alter table public.categories add column if not exists name_en text;
alter table public.categories add column if not exists sort_order integer not null default 0;
alter table public.categories add column if not exists active boolean not null default true;

-- shops
alter table public.shops add column if not exists owner_user_id uuid;
alter table public.shops add column if not exists title text;
alter table public.shops add column if not exists support_username text;
alter table public.shops add column if not exists active boolean not null default true;
alter table public.shops add column if not exists pay_method text default 'stars';
alter table public.shops add column if not exists required_channel_id text;
alter table public.shops add column if not exists required_channel_username text;

-- products   (product_type: digital = file/code sent by the bot, physical = shipped by post)
alter table public.products add column if not exists category_id uuid;
alter table public.products add column if not exists shop_id uuid;
alter table public.products add column if not exists name_fa text;
alter table public.products add column if not exists name_en text;
alter table public.products add column if not exists description_fa text;
alter table public.products add column if not exists description_en text;
alter table public.products add column if not exists image_url text;
alter table public.products add column if not exists price numeric not null default 0;
alter table public.products add column if not exists stars_price integer not null default 0;
alter table public.products add column if not exists stock integer not null default 0;
alter table public.products add column if not exists active boolean not null default true;
alter table public.products add column if not exists pay_method text;
alter table public.products add column if not exists banner_file_id text;
alter table public.products add column if not exists banner_type text;
alter table public.products add column if not exists product_file_id text;
alter table public.products add column if not exists product_file_type text;
alter table public.products add column if not exists digital_content text;
alter table public.products add column if not exists product_type text not null default 'digital';

-- cart
alter table public.cart_items add column if not exists user_id uuid;
alter table public.cart_items add column if not exists product_id uuid;
alter table public.cart_items add column if not exists quantity integer not null default 1;

-- orders  (one order = one seller)
alter table public.orders add column if not exists user_id uuid;
alter table public.orders add column if not exists status text not null default 'pending';
alter table public.orders add column if not exists payment_status text not null default 'unpaid';
alter table public.orders add column if not exists payment_method text;
alter table public.orders add column if not exists subtotal numeric not null default 0;
alter table public.orders add column if not exists total numeric not null default 0;
alter table public.orders add column if not exists transaction_id text;
alter table public.orders add column if not exists shop_id uuid;
alter table public.orders add column if not exists seller_id uuid;
alter table public.orders add column if not exists currency text not null default 'IRT';   -- XTR | IRT | CUSTOM
alter table public.orders add column if not exists requires_shipping boolean not null default false;
alter table public.orders add column if not exists ship_name text;
alter table public.orders add column if not exists ship_phone text;
alter table public.orders add column if not exists ship_address text;
alter table public.orders add column if not exists ship_postal_code text;
alter table public.orders add column if not exists tracking_code text;
alter table public.orders add column if not exists stock_deducted boolean not null default false;
alter table public.orders add column if not exists paid_at timestamptz;
alter table public.orders add column if not exists shipped_at timestamptz;
alter table public.orders add column if not exists completed_at timestamptz;
alter table public.orders add column if not exists cancelled_at timestamptz;

-- order items (snapshot of what was bought)
alter table public.order_items add column if not exists order_id uuid;
alter table public.order_items add column if not exists product_id uuid;
alter table public.order_items add column if not exists product_name text;
alter table public.order_items add column if not exists product_name_en text;
alter table public.order_items add column if not exists quantity integer not null default 1;
alter table public.order_items add column if not exists unit_price numeric not null default 0;
alter table public.order_items add column if not exists digital_delivery text;
alter table public.order_items add column if not exists product_type text not null default 'digital';

-- coupons
alter table public.coupons add column if not exists code text;
alter table public.coupons add column if not exists kind text default 'percent';
alter table public.coupons add column if not exists value numeric not null default 0;
alter table public.coupons add column if not exists active boolean not null default true;
alter table public.coupons add column if not exists expires_at timestamptz;
alter table public.coupons add column if not exists max_uses integer;
alter table public.coupons add column if not exists used_count integer not null default 0;

-- deals (anonymous chat for "custom" payment)
alter table public.deals add column if not exists product_id uuid;
alter table public.deals add column if not exists shop_id uuid;
alter table public.deals add column if not exists customer_id uuid;
alter table public.deals add column if not exists seller_id uuid;
alter table public.deals add column if not exists status text not null default 'open';
alter table public.deals add column if not exists order_id uuid;
alter table public.deals add column if not exists quantity integer not null default 1;

-- reviews / reports   (seq 1..2 + unique index = a person can post at most 2 per product)
alter table public.product_reviews add column if not exists product_id uuid;
alter table public.product_reviews add column if not exists user_id uuid;
alter table public.product_reviews add column if not exists rating integer not null default 5;
alter table public.product_reviews add column if not exists comment text;
alter table public.product_reviews add column if not exists seq smallint;
alter table public.product_reports add column if not exists product_id uuid;
alter table public.product_reports add column if not exists user_id uuid;
alter table public.product_reports add column if not exists reason text;
alter table public.product_reports add column if not exists seq smallint;
alter table public.product_reports add column if not exists status text not null default 'open';

-- plans / subscriptions
alter table public.plans add column if not exists name_fa text;
alter table public.plans add column if not exists name_en text;
alter table public.plans add column if not exists days integer;
alter table public.plans add column if not exists stars integer;
alter table public.plans add column if not exists active boolean not null default true;
alter table public.subscriptions add column if not exists user_id uuid;
alter table public.subscriptions add column if not exists shop_id uuid;
alter table public.subscriptions add column if not exists plan_id uuid;
alter table public.subscriptions add column if not exists status text not null default 'active';
alter table public.subscriptions add column if not exists is_trial boolean not null default false;
alter table public.subscriptions add column if not exists ends_at timestamptz;

-- support / receipts
alter table public.support_messages add column if not exists from_user_id uuid;
alter table public.support_messages add column if not exists shop_id uuid;
alter table public.support_messages add column if not exists target text;
alter table public.support_messages add column if not exists message text;
alter table public.payment_receipts add column if not exists order_id uuid;
alter table public.payment_receipts add column if not exists telegram_id bigint;
alter table public.payment_receipts add column if not exists text text;

-- ---------------------------------------------------------------- 4) data fixes
-- number older reviews/reports per (product,user); only the first 2 get a seq,
-- extra legacy rows keep seq = NULL (kept as history, they simply count toward the limit)
with ranked as (
  select id, row_number() over (partition by product_id, user_id order by created_at, id) as rn
  from public.product_reviews where seq is null
)
update public.product_reviews r set seq = ranked.rn from ranked where r.id = ranked.id and ranked.rn <= 2;
with ranked as (
  select id, row_number() over (partition by product_id, user_id order by created_at, id) as rn
  from public.product_reports where seq is null
)
update public.product_reports r set seq = ranked.rn from ranked where r.id = ranked.id and ranked.rn <= 2;

-- the old bot kept the original product price in `price`; make Stars products consistent
update public.products set stars_price = price::integer where stars_price = 0 and price > 0 and pay_method = 'stars';

-- ---------------------------------------------------------------- 5) constraints & indexes
-- helper: add a check constraint only when it does not exist yet (never fails the script)
create or replace function public._su_add_check(p_table text, p_name text, p_expr text) returns void
language plpgsql as $f$
begin
  if not exists (select 1 from pg_constraint where conname = p_name) then
    execute format('alter table public.%I add constraint %I check (%s)', p_table, p_name, p_expr);
  end if;
exception when others then
  raise notice 'skipped constraint %: %', p_name, sqlerrm;
end $f$;

-- helper: add an index; if existing data violates a UNIQUE index it is skipped with a notice
create or replace function public._su_exec(p_sql text) returns void
language plpgsql as $f$
begin
  execute p_sql;
exception when others then
  raise notice 'skipped: % (%)', p_sql, sqlerrm;
end $f$;

select public._su_add_check('products', 'products_product_type_chk', $$product_type in ('digital','physical')$$);
select public._su_add_check('product_reviews', 'product_reviews_seq_chk', $$seq is null or seq between 1 and 2$$);
select public._su_add_check('product_reports', 'product_reports_seq_chk', $$seq is null or seq between 1 and 2$$);
select public._su_add_check('cart_items', 'cart_items_quantity_chk', $$quantity >= 1$$);
select public._su_add_check('order_items', 'order_items_quantity_chk', $$quantity >= 1$$);

select public._su_exec('create unique index if not exists users_telegram_id_uidx on public.users (telegram_id)');
select public._su_exec('create unique index if not exists shops_owner_uidx on public.shops (owner_user_id)');
select public._su_exec('create unique index if not exists cart_items_user_product_uidx on public.cart_items (user_id, product_id)');
select public._su_exec('create unique index if not exists addresses_user_uidx on public.addresses (user_id)');
select public._su_exec('create unique index if not exists product_reviews_limit_uidx on public.product_reviews (product_id, user_id, seq) where seq is not null');
select public._su_exec('create unique index if not exists product_reports_limit_uidx on public.product_reports (product_id, user_id, seq) where seq is not null');
select public._su_exec('create unique index if not exists coupons_code_uidx on public.coupons (code)');
select public._su_exec('create index if not exists orders_user_idx on public.orders (user_id, created_at desc)');
select public._su_exec('create index if not exists orders_seller_idx on public.orders (seller_id, status, created_at desc)');
select public._su_exec('create index if not exists order_items_order_idx on public.order_items (order_id)');
select public._su_exec('create index if not exists order_items_product_idx on public.order_items (product_id)');
select public._su_exec('create index if not exists deals_order_idx on public.deals (order_id)');
select public._su_exec('create index if not exists deals_open_customer_idx on public.deals (customer_id) where status = ''open''');
select public._su_exec('create index if not exists deals_open_seller_idx on public.deals (seller_id) where status = ''open''');
select public._su_exec('create index if not exists products_shop_idx on public.products (shop_id, active)');
select public._su_exec('create index if not exists subscriptions_user_idx on public.subscriptions (user_id, status)');

-- ---------------------------------------------------------------- 6) foreign keys
-- Added only when no FK already links the same column (a second one would make PostgREST
-- report an ambiguous relationship and break the cart query `cart_items -> products`).
create or replace function public._su_fk(p_table text, p_col text, p_ref text, p_on_delete text default 'no action') returns void
language plpgsql as $f$
begin
  if exists (
    select 1
    from pg_constraint c
    join pg_class t  on t.oid  = c.conrelid
    join pg_namespace n on n.oid = t.relnamespace
    join pg_class rt on rt.oid = c.confrelid
    join pg_attribute a on a.attrelid = c.conrelid and a.attnum = any (c.conkey)
    where c.contype = 'f' and n.nspname = 'public'
      and t.relname = p_table and rt.relname = p_ref and a.attname = p_col
  ) then
    return;
  end if;
  execute format('alter table public.%I add constraint %I foreign key (%I) references public.%I(id) on delete %s',
                 p_table, p_table || '_' || p_col || '_fkey', p_col, p_ref, p_on_delete);
exception when others then
  raise notice 'skipped FK %.% -> %: %', p_table, p_col, p_ref, sqlerrm;
end $f$;

select public._su_fk('shops', 'owner_user_id', 'users', 'cascade');
select public._su_fk('products', 'shop_id', 'shops', 'set null');
select public._su_fk('products', 'category_id', 'categories', 'set null');
select public._su_fk('cart_items', 'user_id', 'users', 'cascade');
select public._su_fk('cart_items', 'product_id', 'products', 'cascade');
select public._su_fk('orders', 'user_id', 'users', 'no action');
select public._su_fk('orders', 'shop_id', 'shops', 'set null');
select public._su_fk('orders', 'seller_id', 'users', 'set null');
select public._su_fk('order_items', 'order_id', 'orders', 'cascade');
select public._su_fk('order_items', 'product_id', 'products', 'set null');
select public._su_fk('deals', 'customer_id', 'users', 'cascade');
select public._su_fk('deals', 'seller_id', 'users', 'cascade');
select public._su_fk('deals', 'order_id', 'orders', 'set null');
select public._su_fk('product_reviews', 'product_id', 'products', 'cascade');
select public._su_fk('product_reviews', 'user_id', 'users', 'cascade');
select public._su_fk('product_reports', 'product_id', 'products', 'cascade');
select public._su_fk('product_reports', 'user_id', 'users', 'cascade');
select public._su_fk('subscriptions', 'user_id', 'users', 'cascade');
select public._su_fk('addresses', 'user_id', 'users', 'cascade');

drop function if exists public._su_fk(text, text, text, text);
drop function if exists public._su_exec(text);
drop function if exists public._su_add_check(text, text, text);

-- ---------------------------------------------------------------- 7) security (RLS)
-- With RLS on and no policy, the public anon key can read nothing.
-- The bot uses the service_role key, which bypasses RLS.
alter table public.users            enable row level security;
alter table public.settings         enable row level security;
alter table public.categories       enable row level security;
alter table public.shops            enable row level security;
alter table public.products         enable row level security;
alter table public.cart_items       enable row level security;
alter table public.orders           enable row level security;
alter table public.order_items      enable row level security;
alter table public.coupons          enable row level security;
alter table public.deals            enable row level security;
alter table public.product_reviews  enable row level security;
alter table public.product_reports  enable row level security;
alter table public.plans            enable row level security;
alter table public.subscriptions    enable row level security;
alter table public.support_messages enable row level security;
alter table public.payment_receipts enable row level security;
alter table public.addresses        enable row level security;
alter table public.bot_states       enable row level security;
alter table public.payments_ledger  enable row level security;
revoke all on table public.addresses, public.bot_states, public.payments_ledger from anon, authenticated;

-- ---------------------------------------------------------------- 8) refresh the API cache
-- without this PostgREST keeps the old schema and the bot says "column not found"
notify pgrst, 'reload schema';
