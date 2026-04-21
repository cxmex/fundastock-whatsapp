-- Sales Agent tables for Fundastock WhatsApp bot
-- Run against Supabase direct connection:
--   psql "postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres" -f migrations/001_sales_agent.sql

-- Conversation state per phone number
CREATE TABLE IF NOT EXISTS whatsapp_conversations (
  phone_number TEXT PRIMARY KEY,
  lead_source TEXT,                    -- 'fb_ad' | 'tiktok_ad' | 'organic' | 'walk_in'
  campaign_id TEXT,                    -- Meta ad_id if from Click-to-WhatsApp
  ad_headline TEXT,
  ad_body TEXT,
  lead_type TEXT DEFAULT 'unknown',    -- 'unknown' | 'retail' | 'wholesale' | 'existing_customer'
  stage TEXT DEFAULT 'greeting',       -- 'greeting'|'qualifying'|'product_selection'|'closing'|'post_sale'|'escalated'|'completed'
  captured_data JSONB DEFAULT '{}',    -- { modelo, color, cantidad, shipping_address, rfc, ... }
  last_message_at TIMESTAMPTZ DEFAULT NOW(),
  escalated BOOLEAN DEFAULT FALSE,
  human_takeover BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Turn-by-turn sales conversation log (separate from existing whatsapp_messages)
CREATE TABLE IF NOT EXISTS sales_conversation_turns (
  id BIGSERIAL PRIMARY KEY,
  phone_number TEXT NOT NULL,
  role TEXT NOT NULL,                  -- 'user' | 'assistant' | 'tool'
  content TEXT,
  tool_name TEXT,
  tool_args JSONB,
  tool_result JSONB,
  stage_at_turn TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sct_phone_created ON sales_conversation_turns(phone_number, created_at DESC);

-- Orders created by the sales agent
CREATE TABLE IF NOT EXISTS sales_orders (
  id BIGSERIAL PRIMARY KEY,
  phone_number TEXT NOT NULL,
  lead_source TEXT,
  campaign_id TEXT,
  order_type TEXT,                     -- 'retail' | 'wholesale'
  items JSONB NOT NULL,                -- [{ modelo, estilo, color_id, cantidad, precio_unit }]
  subtotal NUMERIC,
  shipping_cost NUMERIC,
  total NUMERIC,
  expected_amount NUMERIC NOT NULL,    -- total WITH cents fingerprint, this is what customer must pay
  payment_method TEXT CHECK (payment_method IN ('spei', 'oxxo_tarjeta')),
  payment_status TEXT DEFAULT 'pending',   -- 'pending' | 'payment_claimed' | 'paid' | 'expired' | 'refunded'
  payment_instructions_sent_at TIMESTAMPTZ,
  payment_claimed_at TIMESTAMPTZ,
  payment_comprobante_url TEXT,
  payment_comprobante_extracted JSONB,
  payment_verified_at TIMESTAMPTZ,
  payment_verified_by TEXT,
  shipping_address JSONB,
  rfc TEXT,
  razon_social TEXT,
  uso_cfdi TEXT,
  email_factura TEXT,
  tracking_number TEXT,
  shipping_provider TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  paid_at TIMESTAMPTZ,
  shipped_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_so_phone ON sales_orders(phone_number);
CREATE INDEX IF NOT EXISTS idx_so_status ON sales_orders(payment_status);
CREATE INDEX IF NOT EXISTS idx_so_expected_amount ON sales_orders(expected_amount) WHERE payment_status IN ('pending', 'payment_claimed');
