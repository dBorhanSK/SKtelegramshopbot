create extension if not exists "pgcrypto";

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  telegram_id bigint unique not null,
  username text,
  first_name text,
  language text default 'fa',
  role text default 'user',
  wallet_balance numeric default 0,
  points integer default 0,
  created_at timestamptz default now()
);

create table if not exists categories (
  id uuid primary key default gen_random_uuid(),
  parent_id uuid references categories(id) on delete cascade,
  name_fa text not null,
  name_en text not null,
  sort_order integer default 0,
  active boolean default true,
  created_at timestamptz default now()
);

create table if not exists products (
  id uuid primary key default gen_random_uuid(),
  category_id uuid references categories(id) on delete set null,
  name_fa text not null,
  name_en text not null,
  description_fa text default '',
  description_en text default '',
  image_url text,
  price numeric not null default 0,
  stock integer default 0,
  digital_content text,
  active boolean default true,
  created_at timestamptz default now()
);

create table if not exists cart_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  product_id uuid references products(id) on delete cascade,
  quantity integer not null default 1,
  unique(user_id, product_id)
);

create table if not exists orders (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id),
  status text default 'pending',
  payment_status text default 'unpaid',
  payment_method text,
  transaction_id text,
  subtotal numeric default 0,
  discount numeric default 0,
  total numeric default 0,
  coupon_code text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists order_items (
  id uuid primary key default gen_random_uuid(),
  order_id uuid references orders(id) on delete cascade,
  product_id uuid references products(id),
  product_name text,
  quantity integer default 1,
  unit_price numeric default 0,
  digital_delivery text
);

create table if not exists coupons (
  id uuid primary key default gen_random_uuid(),
  code text unique not null,
  kind text default 'percent',
  value numeric default 0,
  max_uses integer,
  used_count integer default 0,
  expires_at timestamptz,
  active boolean default true
);

create table if not exists payment_receipts (
  id uuid primary key default gen_random_uuid(),
  order_id uuid references orders(id) on delete cascade,
  telegram_id bigint,
  text text,
  created_at timestamptz default now()
);

create table if not exists tickets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id),
  message text,
  status text default 'open',
  admin_reply text,
  created_at timestamptz default now()
);

create table if not exists channel_prices (
  id uuid primary key default gen_random_uuid(),
  channel_name text not null,
  ad_type text not null,
  price numeric not null,
  description text default '',
  active boolean default true
);

create index if not exists idx_orders_user on orders(user_id);
create index if not exists idx_orders_created on orders(created_at);
create index if not exists idx_products_category on products(category_id);
