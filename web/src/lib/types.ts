export type LocaleCode = 'ru' | 'en';

export interface BackendErrorPayload {
  code?: string;
  message?: string;
  [key: string]: unknown;
}

export interface BackendResponse<T = Record<string, unknown>> {
  ok: boolean;
  error?: BackendErrorPayload;
  [key: string]: unknown;
}

export interface PublicConfig {
  web_app_url: string | null;
  bot_username: string | null;
  default_language: LocaleCode;
  support_link: string | null;
  privacy_policy_url: string | null;
  terms_of_service_url: string | null;
  user_agreement_url: string | null;
  email_auth_enabled: boolean;
  trial_enabled: boolean;
  traffic_sale_mode: boolean;
  my_devices_enabled: boolean;
  yookassa_enabled: boolean;
  yookassa_autopayments_enabled: boolean;
  cryptopay_enabled: boolean;
  freekassa_enabled: boolean;
  platega_enabled: boolean;
  severpay_enabled: boolean;
  stars_enabled: boolean;
  payment_methods_order: string[];
}

export interface UserSummary {
  id: number;
  email: string | null;
  email_verified_at: string | null;
  telegram_user_id: number | null;
  telegram_linked_at: string | null;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  display_name: string;
  language_code: string | null;
  registration_date: string | null;
  is_banned: boolean;
  panel_user_uuid: string | null;
  referral_code: string | null;
  referred_by_id: number | null;
  lifetime_used_traffic_bytes: number | null;
  lifetime_used_traffic_gb: number | null;
  channel_subscription_verified: boolean | null;
}

export interface SubscriptionSummary {
  subscription_id?: number;
  panel_user_uuid?: string;
  panel_subscription_uuid?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  duration_months?: number | null;
  is_active?: boolean;
  status_from_panel?: string | null;
  traffic_limit_bytes?: number | null;
  traffic_limit_gb?: number | null;
  traffic_used_bytes?: number | null;
  traffic_used_gb?: number | null;
  provider?: string | null;
  skip_notifications?: boolean;
  auto_renew_enabled?: boolean;
  last_notification_sent?: string | null;
  config_link?: string | null;
  connect_button_url?: string | null;
  max_devices?: number | null;
  user_id?: string | number;
  days_left?: number | null;
}

export interface PaymentMethodSummary {
  id: number;
  provider: string;
  provider_payment_method_id: string;
  card_last4: string | null;
  card_network: string | null;
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface PaymentSummary {
  id: number;
  provider: string;
  provider_label: string;
  provider_payment_id: string | null;
  yookassa_payment_id: string | null;
  amount: number;
  amount_display: string;
  currency: string;
  status: string;
  description: string | null;
  subscription_duration_months: number | null;
  created_at: string | null;
  created_at_short: string | null;
  updated_at: string | null;
}

export interface DeviceSummary {
  index: number;
  hwid_token: string | null;
  hwid_masked: string | null;
  device_model: string | null;
  platform: string | null;
  os_version: string | null;
  user_agent: string | null;
  created_at: string | null;
  created_at_short: string | null;
  hwid: string | null;
}

export interface PlanItem {
  units: number;
  units_display: string;
  unit_label: string;
  cash_price: number | null;
  stars_price: number | null;
  cash_currency: string;
  stars_currency: string;
  cash_enabled: boolean;
  stars_enabled: boolean;
}

export interface ProviderItem {
  key: string;
  label: string;
  enabled: boolean;
  supports_saved_cards?: boolean;
  requires_telegram?: boolean;
}

export interface DashboardData {
  user: UserSummary;
  subscription: SubscriptionSummary | null;
  payment_methods: PaymentMethodSummary[];
  payments: PaymentSummary[];
  referral: {
    stats: { invited_count: number; purchased_count: number };
    link: string | null;
    bonus_inviter: Record<string, number>;
    bonus_referee: Record<string, number>;
    welcome_bonus_days: number;
    one_bonus_per_referee: boolean;
  };
  trial: {
    enabled: boolean;
    available: boolean;
    duration_days: number;
    traffic_limit_gb: number | null;
  };
  devices: {
    enabled: boolean;
    items: DeviceSummary[];
    count: number;
    max_devices: number | null;
  };
  plans: {
    traffic_mode: boolean;
    units_label: string;
    plans: PlanItem[];
    providers: ProviderItem[];
  };
  feature_flags: {
    yookassa_autopayments_active: boolean;
    my_devices_enabled: boolean;
    trial_enabled: boolean;
    traffic_sale_mode: boolean;
    stars_enabled: boolean;
  };
  links: {
    support: string | null;
    privacy_policy: string | null;
    terms_of_service: string | null;
    user_agreement: string | null;
    web_app: string | null;
  };
}

export interface BootstrapData {
  authenticated: boolean;
  public: PublicConfig;
  server_time: string;
  session?: {
    expires_at: string | null;
    auth_method: string | null;
    last_seen_at: string | null;
  };
  user?: UserSummary;
}

export interface DashboardResponse extends BootstrapData {
  dashboard?: DashboardData;
}

export interface PortalActionResponse<T = Record<string, unknown>> {
  ok: boolean;
  error?: BackendErrorPayload;
  [key: string]: unknown;
  result?: T;
}
