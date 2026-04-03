<script lang="ts">
  import { browser } from '$app/environment';
  import { goto, invalidateAll } from '$app/navigation';
  import { onMount } from 'svelte';
  import { portalAction, PortalError } from '$lib/client/api';
  import { portalCopy, tr } from '$lib/portal-copy';
  import type {
    DashboardData,
    DeviceSummary,
    LocaleCode,
    PlanItem,
    ProviderItem,
  } from '$lib/types';
  import type { PageData } from './$types';

  type PortalCopyKey = keyof typeof portalCopy.en;
  type Banner = { kind: 'success' | 'error' | 'info'; text: string };

  export let data: PageData;

  let bootstrap = data.bootstrap;
  let dashboard: DashboardData | null = data.dashboard;
  let dashboardError = data.dashboardError ?? null;
  let locale: LocaleCode = bootstrap.authenticated
    ? ((dashboard?.user.language_code as LocaleCode | null | undefined) ?? bootstrap.public.default_language)
    : bootstrap.public.default_language;

  let banner: Banner | null = null;
  let busyAction: string | null = null;
  let loginEmail = bootstrap.user?.email ?? '';
  let loginCode = '';
  let telegramLoginCode = data.telegramCode ?? '';
  let emailLinkTarget = '';
  let emailLinkCode = '';
  let telegramLinkCode = '';
  let telegramLinkUrl: string | null = null;
  let promoCode = '';
  let telegramAutoAttempted = false;

  $: bootstrap = data.bootstrap;
  $: dashboard = data.dashboard;
  $: dashboardError = data.dashboardError ?? null;
  $: locale = bootstrap.authenticated
    ? ((dashboard?.user.language_code as LocaleCode | null | undefined) ?? bootstrap.public.default_language)
    : bootstrap.public.default_language;

  function copyText(key: PortalCopyKey, vars: Record<string, string | number> = {}): string {
    return tr(locale, key, vars);
  }

  function formatNumber(value: number | string | null | undefined): string {
    if (value === null || value === undefined || value === '') return '—';
    const numeric = typeof value === 'number' ? value : Number(value);
    if (Number.isNaN(numeric)) return String(value);
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(numeric);
  }

  function formatDateTime(value: string | null | undefined): string {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date);
  }

  function formatDate(value: string | null | undefined): string {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(date);
  }

  function formatBytes(value: number | null | undefined): string {
    if (value === null || value === undefined) return '—';
    const gigabytes = value / (1024 ** 3);
    return `${formatNumber(gigabytes)} GB`;
  }

  function formatCurrencyValue(value: number | string | null | undefined, currency: string): string {
    if (value === null || value === undefined || value === '') return '—';
    const amount = typeof value === 'number' ? value : Number(value);
    if (Number.isNaN(amount)) return `${value} ${currency}`;
    if (currency === '⭐') {
      return `${formatNumber(amount)} ⭐`;
    }
    return `${formatNumber(amount)} ${currency}`;
  }

  function statusTone(status: string | null | undefined): 'ok' | 'warn' | 'bad' {
    const value = (status || '').toLowerCase();
    if (['active', 'succeeded', 'success', 'enabled', 'linked', 'paid', 'completed'].includes(value)) return 'ok';
    if (['failed', 'error', 'inactive', 'canceled', 'cancelled', 'disabled'].includes(value)) return 'bad';
    return 'warn';
  }

  function badgeClass(status: string | null | undefined): string {
    const tone = statusTone(status);
    if (tone === 'ok') return 'status-ok';
    if (tone === 'bad') return 'status-bad';
    return 'status-warn';
  }

  function getResponseMessage(response: unknown, fallback: string): string {
    if (response && typeof response === 'object' && 'message' in response) {
      const message = (response as { message?: unknown }).message;
      if (typeof message === 'string' && message.trim()) {
        return message;
      }
    }
    return fallback;
  }

  async function callAction<T = Record<string, unknown>>(action: string, payload: Record<string, unknown>): Promise<T | null> {
    busyAction = action;
    try {
      return await portalAction<T>(action, payload);
    } catch (error) {
      banner = {
        kind: 'error',
        text: error instanceof PortalError ? error.message : error instanceof Error ? error.message : String(error),
      };
      return null;
    } finally {
      busyAction = null;
    }
  }

  async function refreshDashboard(): Promise<void> {
    await invalidateAll();
  }

  async function copyValue(value: string | null | undefined): Promise<void> {
    if (!browser || !value) return;
    await navigator.clipboard.writeText(value);
    banner = { kind: 'success', text: copyText('copied') };
  }

  function defaultYookassaMethodId(): number | null {
    const methods = dashboard?.payment_methods.filter((method) => method.provider === 'yookassa') ?? [];
    const preferred = methods.find((method) => method.is_default) ?? methods[0];
    return preferred?.id ?? null;
  }

  function canBuy(plan: PlanItem, provider: ProviderItem): boolean {
    if (!provider.enabled) return false;
    if (provider.key === 'stars') return plan.stars_enabled;
    return plan.cash_enabled;
  }

  function planPrice(plan: PlanItem, provider: ProviderItem): string {
    if (provider.key === 'stars') {
      return formatCurrencyValue(plan.stars_price, plan.stars_currency);
    }
    return formatCurrencyValue(plan.cash_price, plan.cash_currency);
  }

  async function requestEmailCode(purpose: 'email_auth' | 'email_link'): Promise<void> {
    const email = (purpose === 'email_auth' ? loginEmail : emailLinkTarget).trim();
    if (!email) {
      banner = { kind: 'error', text: copyText('emailLabel') };
      return;
    }

    const response = await callAction<{
      already_linked?: boolean;
      resend_limited?: boolean;
      cooldown_remaining?: number;
    }>('auth.email.request', {
      email,
      purpose,
      language_code: locale,
    });
    if (!response) return;

    if (response.already_linked) {
      banner = { kind: 'info', text: copyText('emailStatusLinked') };
      return;
    }

    if (purpose === 'email_auth') {
      loginCode = '';
    } else {
      emailLinkCode = '';
    }

    banner = {
      kind: 'success',
      text: response.resend_limited
        ? copyText('cooldownRemaining', { value: response.cooldown_remaining ?? 0 })
        : copyText('emailCodeSent'),
    };
  }

  async function verifyEmailCode(purpose: 'email_auth' | 'email_link'): Promise<void> {
    const email = (purpose === 'email_auth' ? loginEmail : emailLinkTarget).trim();
    const code = (purpose === 'email_auth' ? loginCode : emailLinkCode).trim();
    if (!email || !code) {
      banner = { kind: 'error', text: copyText('verifyCode') };
      return;
    }

    const response = await callAction<{
      session_token?: string;
      email_linked?: boolean;
    }>('auth.email.verify', {
      email,
      code,
      purpose,
      language_code: locale,
    });
    if (!response) return;

    if (purpose === 'email_link' && response.email_linked) {
      emailLinkCode = '';
      banner = { kind: 'success', text: copyText('emailStatusLinked') };
      await refreshDashboard();
      return;
    }

    if (response.session_token) {
      loginCode = '';
      banner = { kind: 'success', text: copyText('heroStatusAuthenticated') };
      await refreshDashboard();
      return;
    }

    banner = { kind: 'info', text: getResponseMessage(response, copyText('verifyCode')) };
  }

  async function verifyTelegramCode(clearQuery = false): Promise<void> {
    const code = telegramLoginCode.trim();
    if (!code) {
      banner = { kind: 'error', text: copyText('telegramCodeLabel') };
      return;
    }

    const response = await callAction<{
      session_token?: string;
      linked?: boolean;
    }>('auth.telegram.verify', {
      code,
      purpose: 'web_login',
      language_code: locale,
    });
    if (!response) return;

    if (response.linked) {
      telegramLoginCode = '';
      banner = { kind: 'success', text: copyText('telegramStatusLinked') };
      await refreshDashboard();
      return;
    }

    if (response.session_token) {
      telegramLoginCode = '';
      banner = { kind: 'success', text: copyText('heroStatusAuthenticated') };
      if (browser && clearQuery) {
        const url = new URL(window.location.href);
        url.searchParams.delete('telegram_code');
        await goto(`${url.pathname}${url.search}`, {
          replaceState: true,
          invalidateAll: true,
          noScroll: true,
          keepFocus: true,
        });
        return;
      }
      await refreshDashboard();
      return;
    }

    banner = { kind: 'info', text: getResponseMessage(response, copyText('verifyCode')) };
  }

  async function requestTelegramLink(): Promise<void> {
    const response = await callAction<{
      already_linked?: boolean;
      code?: string | null;
      link_url?: string | null;
    }>('auth.telegram.request-link', { language_code: locale });
    if (!response) return;

    if (response.already_linked) {
      telegramLinkCode = '';
      telegramLinkUrl = null;
      banner = { kind: 'info', text: copyText('telegramStatusLinked') };
      return;
    }

    telegramLinkCode = response.code ?? '';
    telegramLinkUrl = response.link_url ?? null;
    banner = { kind: 'success', text: copyText('telegramCodeReady') };
  }

  async function setLanguage(nextLocale: LocaleCode): Promise<void> {
    const response = await callAction('profile.language.set', { language_code: nextLocale });
    if (!response) return;
    banner = { kind: 'success', text: `${copyText('languageLabel')}: ${nextLocale}` };
    await refreshDashboard();
  }

  async function applyPromo(): Promise<void> {
    const code = promoCode.trim();
    if (!code) {
      banner = { kind: 'error', text: copyText('promoPlaceholder') };
      return;
    }
    const response = await callAction('promo.apply', { code, language_code: locale });
    if (!response) return;
    promoCode = '';
    banner = { kind: 'success', text: getResponseMessage(response, copyText('applyPromo')) };
    await refreshDashboard();
  }

  async function activateTrial(): Promise<void> {
    const response = await callAction('trial.activate', {});
    if (!response) return;
    banner = { kind: 'success', text: getResponseMessage(response, copyText('activateTrial')) };
    await refreshDashboard();
  }

  async function setAutorenew(enabled: boolean): Promise<void> {
    const response = await callAction('subscription.autorenew.set', { enabled });
    if (!response) return;
    banner = { kind: 'success', text: enabled ? copyText('enableAutoRenew') : copyText('disableAutoRenew') };
    await refreshDashboard();
  }

  async function bindCard(): Promise<void> {
    const response = await callAction<{ url?: string; message?: string }>('payment-methods.bind', {});
    if (!response) return;
    if (response.url && browser) {
      banner = { kind: 'info', text: getResponseMessage(response, copyText('bindCard')) };
      window.location.assign(response.url);
      return;
    }
    banner = { kind: 'info', text: getResponseMessage(response, copyText('bindCard')) };
  }

  async function setDefaultMethod(methodId: number): Promise<void> {
    const response = await callAction('payment-methods.set-default', { method_id: methodId });
    if (!response) return;
    banner = { kind: 'success', text: copyText('defaultMethod') };
    await refreshDashboard();
  }

  async function deleteMethod(methodId: number): Promise<void> {
    const response = await callAction('payment-methods.delete', { method_id: methodId });
    if (!response) return;
    banner = { kind: 'success', text: copyText('delete') };
    await refreshDashboard();
  }

  async function disconnectDevice(device: DeviceSummary): Promise<void> {
    if (!device.hwid_token) return;
    const response = await callAction('devices.disconnect', { hwid_token: device.hwid_token });
    if (!response) return;
    banner = { kind: 'success', text: copyText('disconnect') };
    await refreshDashboard();
  }

  async function purchasePlan(plan: PlanItem, provider: ProviderItem): Promise<void> {
    const payload: Record<string, unknown> = {
      provider: provider.key,
      units: plan.units,
    };
    if (provider.key === 'yookassa') {
      const methodId = defaultYookassaMethodId();
      if (methodId !== null) {
        payload.payment_method_id = methodId;
      }
    }

    const response = await callAction<{
      kind?: 'redirect' | 'charge_initiated' | 'telegram_invoice';
      url?: string | null;
      message?: string;
    }>('purchase.create', payload);
    if (!response) return;

    if (response.kind === 'redirect' && response.url) {
      banner = { kind: 'info', text: getResponseMessage(response, copyText('paymentLinkReady')) };
      if (browser) {
        window.location.assign(response.url);
      }
      return;
    }

    if (response.kind === 'telegram_invoice') {
      banner = { kind: 'info', text: getResponseMessage(response, copyText('invoiceSent')) };
      await refreshDashboard();
      return;
    }

    if (response.kind === 'charge_initiated') {
      banner = { kind: 'info', text: getResponseMessage(response, copyText('chargeInitiated')) };
      await refreshDashboard();
      return;
    }

    banner = { kind: 'info', text: getResponseMessage(response, copyText('buyNow')) };
  }

  onMount(async () => {
    if (telegramLoginCode.trim() && !bootstrap.authenticated && !telegramAutoAttempted) {
      telegramAutoAttempted = true;
      await verifyTelegramCode(true);
    }
  });

  function providerButtonLabel(plan: PlanItem, provider: ProviderItem): string {
    return `${provider.label} · ${planPrice(plan, provider)}`;
  }
</script>

<svelte:head>
  <title>{copyText('appName')}</title>
  <meta name="description" content={copyText('appTagline')} />
</svelte:head>

<div class="shell">
  <section class="card hero">
    <div class="card-inner hero-grid">
      <div class="hero-copy">
        <div class="pill">{copyText('appName')}</div>
        <h1 class="title hero-title">{copyText('appName')}</h1>
        <p class="hero-lead muted">{copyText('appTagline')}</p>
        <div class="hero-badges">
          <span class="pill">{copyText('heroStatusLabel')}: {bootstrap.authenticated ? copyText('heroStatusAuthenticated') : copyText('heroStatusGuest')}</span>
          {#if bootstrap.authenticated && bootstrap.session}
            <span class="pill">{copyText('sessionExpires', { value: formatDateTime(bootstrap.session.expires_at) })}</span>
            <span class="pill">{copyText('authMethod', { value: bootstrap.session.auth_method ?? 'email' })}</span>
          {/if}
        </div>
      </div>

      <div class="hero-aside">
        {#if bootstrap.authenticated && dashboard?.user}
          <div class="metric-grid">
            <div class="metric">
              <span class="tiny">{copyText('emailLabel')}</span>
              <strong>{dashboard.user.email ?? copyText('emailStatusMissing')}</strong>
            </div>
            <div class="metric">
              <span class="tiny">{copyText('telegramTitle')}</span>
              <strong>{dashboard.user.telegram_user_id ? copyText('telegramStatusLinked') : copyText('telegramStatusMissing')}</strong>
            </div>
          </div>
        {:else}
          <p class="tiny">{copyText('portalHint')}</p>
        {/if}
        <div class="hero-actions">
          {#if bootstrap.public.bot_username}
            <a class="btn btn-secondary" href={`https://t.me/${bootstrap.public.bot_username}`} target="_blank" rel="noreferrer">{copyText('openBot')}</a>
          {/if}
          {#if bootstrap.authenticated}
            <button
              class="btn btn-ghost"
              type="button"
              on:click={async () => {
                const response = await callAction('auth.logout', {});
                if (!response) return;
                banner = { kind: 'success', text: copyText('logout') };
                await refreshDashboard();
              }}
              disabled={busyAction !== null}
            >
              {copyText('logout')}
            </button>
          {/if}
        </div>
      </div>
    </div>
  </section>

  {#if banner}
    <section class={`card banner-card banner-${banner.kind}`}>
      <div class="card-inner banner-inner">
        <strong>{banner.kind === 'error' ? copyText('statusFailed') : banner.kind === 'success' ? copyText('statusSucceeded') : copyText('statusPending')}</strong>
        <span>{banner.text}</span>
      </div>
    </section>
  {/if}

  {#if dashboardError}
    <section class="card">
      <div class="card-inner stack">
        <div class="section-head">
          <h2 class="title">{copyText('dashboardTitle')}</h2>
          <button class="btn btn-secondary" type="button" on:click={refreshDashboard}>{copyText('retry')}</button>
        </div>
        <p class="status-bad">{dashboardError}</p>
      </div>
    </section>
  {/if}

  {#if !bootstrap.authenticated}
    <div class="grid login-grid">
      <section class="card">
        <div class="card-inner stack">
          <div class="section-head">
            <h2 class="title">{copyText('loginTitle')}</h2>
          </div>
          <p class="muted">{copyText('loginLead')}</p>
          <div class="field">
            <label class="tiny" for="login-email">{copyText('emailLabel')}</label>
            <input
              id="login-email"
              class="input"
              type="email"
              bind:value={loginEmail}
              placeholder={copyText('emailPlaceholder')}
              autocomplete="email"
            />
          </div>
          <div class="field">
            <label class="tiny" for="login-code">{copyText('emailCodeLabel')}</label>
            <input
              id="login-code"
              class="input"
              type="text"
              bind:value={loginCode}
              placeholder={copyText('emailCodePlaceholder')}
              inputmode="numeric"
              autocomplete="one-time-code"
            />
          </div>
          <div class="button-row">
            <button class="btn btn-secondary" type="button" on:click={() => requestEmailCode('email_auth')} disabled={busyAction !== null || !bootstrap.public.email_auth_enabled}>{copyText('requestCode')}</button>
            <button class="btn btn-primary" type="button" on:click={() => verifyEmailCode('email_auth')} disabled={busyAction !== null || !bootstrap.public.email_auth_enabled}>{copyText('verifyCode')}</button>
          </div>
          {#if !bootstrap.public.email_auth_enabled}
            <p class="tiny status-warn">{copyText('emailAuthDisabled')}</p>
          {:else}
            <p class="tiny">{copyText('emailRegistrationNote')}</p>
          {/if}
        </div>
      </section>

      <section class="card">
        <div class="card-inner stack">
          <div class="section-head">
            <h2 class="title">{copyText('telegramTitle')}</h2>
          </div>
          <p class="muted">{copyText('telegramLead')}</p>
          <div class="field">
            <label class="tiny" for="telegram-login-code">{copyText('telegramCodeLabel')}</label>
            <input
              id="telegram-login-code"
              class="input"
              type="text"
              bind:value={telegramLoginCode}
              placeholder={copyText('telegramCodePlaceholder')}
              inputmode="numeric"
              autocomplete="one-time-code"
            />
          </div>
          <div class="button-row">
            <button class="btn btn-primary" type="button" on:click={() => verifyTelegramCode(false)} disabled={busyAction !== null}>{copyText('loginWithTelegramCode')}</button>
            {#if bootstrap.public.bot_username}
              <a class="btn btn-secondary" href={`https://t.me/${bootstrap.public.bot_username}`} target="_blank" rel="noreferrer">{copyText('openBot')}</a>
            {/if}
          </div>
          <p class="tiny">{copyText('telegramDeepLinkNote')}</p>
        </div>
      </section>
    </div>
  {/if}

  <!-- DASHBOARD -->

  {#if bootstrap.authenticated && dashboard}
    <section class="card">
      <div class="card-inner stack">
        <div class="section-head">
          <div>
            <h2 class="title">{copyText('profileCardTitle')}</h2>
            <p class="tiny">{copyText('dashboardSubtitle')}</p>
          </div>
          <div class="hero-actions">
            <label class="language-switch">
              <span class="tiny">{copyText('languageLabel')}</span>
              <select class="select" value={locale} on:change={(event) => setLanguage((event.currentTarget as HTMLSelectElement).value as LocaleCode)}>
                <option value="ru">{copyText('languageRu')}</option>
                <option value="en">{copyText('languageEn')}</option>
              </select>
            </label>
          </div>
        </div>

        <div class="profile-grid">
          <div class="stack">
            <div class="info-line"><span class="tiny">{copyText('emailLabel')}</span><strong>{dashboard.user.email ?? copyText('emailStatusMissing')}</strong></div>
            <div class="info-line"><span class="tiny">{copyText('telegramTitle')}</span><strong>{dashboard.user.telegram_user_id ? copyText('telegramStatusLinked') : copyText('telegramStatusMissing')}</strong></div>
            <div class="info-line"><span class="tiny">{copyText('registrationDate')}</span><strong>{formatDateTime(dashboard.user.registration_date)}</strong></div>
            <div class="info-line"><span class="tiny">{copyText('userId', { value: dashboard.user.id })}</span><strong>{dashboard.user.id}</strong></div>
            <div class="info-line"><span class="tiny">{copyText('referralCode', { value: dashboard.user.referral_code ?? '—' })}</span><strong>{dashboard.user.referral_code ?? '—'}</strong></div>
            <div class="info-line"><span class="tiny">{copyText('panelUserUuid', { value: dashboard.user.panel_user_uuid ?? '—' })}</span><strong>{dashboard.user.panel_user_uuid ?? '—'}</strong></div>
            {#if dashboard.user.email_verified_at}
              <div class="info-line"><span class="tiny">{copyText('verifiedAt', { value: formatDateTime(dashboard.user.email_verified_at) })}</span><strong>{formatDateTime(dashboard.user.email_verified_at)}</strong></div>
            {/if}
            {#if dashboard.user.telegram_linked_at}
              <div class="info-line"><span class="tiny">{copyText('linkedAt', { value: formatDateTime(dashboard.user.telegram_linked_at) })}</span><strong>{formatDateTime(dashboard.user.telegram_linked_at)}</strong></div>
            {/if}
          </div>

          <div class="stack">
            <div class="section-head">
              <h3 class="title">{copyText('linkEmail')}</h3>
            </div>
            <div class="field">
              <label class="tiny" for="link-email">{copyText('emailLabel')}</label>
              <input
                id="link-email"
                class="input"
                type="email"
                bind:value={emailLinkTarget}
                placeholder={copyText('emailPlaceholder')}
                autocomplete="email"
              />
            </div>
            <div class="field">
              <label class="tiny" for="link-email-code">{copyText('emailCodeLabel')}</label>
              <input
                id="link-email-code"
                class="input"
                type="text"
                bind:value={emailLinkCode}
                placeholder={copyText('emailCodePlaceholder')}
                inputmode="numeric"
                autocomplete="one-time-code"
              />
            </div>
            <div class="button-row">
              <button class="btn btn-secondary" type="button" on:click={() => requestEmailCode('email_link')} disabled={busyAction !== null || !bootstrap.public.email_auth_enabled}>{copyText('requestCode')}</button>
              <button class="btn btn-primary" type="button" on:click={() => verifyEmailCode('email_link')} disabled={busyAction !== null || !bootstrap.public.email_auth_enabled}>{copyText('verifyCode')}</button>
            </div>
          </div>

          <div class="stack">
            <div class="section-head">
              <h3 class="title">{copyText('linkTelegram')}</h3>
            </div>
            <p class="tiny">{copyText('telegramDeepLinkNote')}</p>
            <div class="button-row">
              <button class="btn btn-primary" type="button" on:click={requestTelegramLink} disabled={busyAction !== null}>{copyText('requestTelegramLink')}</button>
              {#if bootstrap.public.bot_username}
                <a class="btn btn-secondary" href={`https://t.me/${bootstrap.public.bot_username}`} target="_blank" rel="noreferrer">{copyText('openBot')}</a>
              {/if}
            </div>
            {#if telegramLinkCode}
              <div class="stack">
                <div class="info-line"><span class="tiny">{copyText('telegramCodeLabel')}</span><strong>{telegramLinkCode}</strong></div>
                <div class="button-row">
                  <button class="btn btn-secondary" type="button" on:click={() => copyValue(telegramLinkCode)}>{copyText('copy')}</button>
                  {#if telegramLinkUrl}
                    <a class="btn btn-secondary" href={telegramLinkUrl} target="_blank" rel="noreferrer">{copyText('openBot')}</a>
                  {/if}
                </div>
              </div>
            {/if}
          </div>
        </div>
      </div>
    </section>

    <div class="grid dashboard-grid">
      <section class="card">
        <div class="card-inner stack">
          <div class="section-head">
            <h2 class="title">{copyText('subscriptionCardTitle')}</h2>
            {#if dashboard.subscription}
              <span class={`pill ${badgeClass(dashboard.subscription.status_from_panel ?? dashboard.subscription.provider ?? '')}`}>{dashboard.subscription.is_active ? copyText('subscriptionActive') : copyText('subscriptionInactive')}</span>
            {/if}
          </div>
          {#if dashboard.subscription}
            <div class="metric-grid">
              <div class="metric">
                <span class="tiny">{copyText('expiresAt', { value: formatDateTime(dashboard.subscription.end_date ?? null) })}</span>
                <strong>{formatDateTime(dashboard.subscription.end_date ?? null)}</strong>
              </div>
              <div class="metric">
                <span class="tiny">{copyText('daysLeft', { value: dashboard.subscription.days_left ?? 0 })}</span>
                <strong>{dashboard.subscription.days_left ?? 0}</strong>
              </div>
              <div class="metric">
                <span class="tiny">{copyText('trafficLimit', { value: formatBytes(dashboard.subscription.traffic_limit_bytes ?? null) })}</span>
                <strong>{formatBytes(dashboard.subscription.traffic_limit_bytes ?? null)}</strong>
              </div>
              <div class="metric">
                <span class="tiny">{copyText('trafficUsed', { value: formatBytes(dashboard.subscription.traffic_used_bytes ?? null) })}</span>
                <strong>{formatBytes(dashboard.subscription.traffic_used_bytes ?? null)}</strong>
              </div>
            </div>
            <div class="stack">
              {#if dashboard.subscription.config_link}
                <div class="info-line">
                  <span class="tiny">{copyText('configLink')}</span>
                  <div class="inline-actions">
                    <strong class="truncate">{dashboard.subscription.config_link}</strong>
                    <button class="btn btn-secondary" type="button" on:click={() => copyValue(dashboard.subscription?.config_link ?? null)}>{copyText('copy')}</button>
                  </div>
                </div>
              {/if}
              {#if dashboard.subscription.connect_button_url}
                <a class="btn btn-primary" href={dashboard.subscription.connect_button_url} target="_blank" rel="noreferrer">{copyText('connectButton')}</a>
              {/if}
              {#if dashboard.subscription.provider === 'yookassa' && bootstrap.public.yookassa_autopayments_enabled}
                <div class="button-row">
                  <button
                    class="btn btn-secondary"
                    type="button"
                    on:click={() => setAutorenew(!(dashboard.subscription?.auto_renew_enabled ?? false))}
                    disabled={busyAction !== null || (!dashboard.subscription?.auto_renew_enabled && !defaultYookassaMethodId())}
                  >
                    {dashboard.subscription.auto_renew_enabled ? copyText('disableAutoRenew') : copyText('enableAutoRenew')}
                  </button>
                  {#if !defaultYookassaMethodId()}
                    <span class="tiny">{copyText('autoRenewNeedsCard')}</span>
                  {/if}
                </div>
              {/if}
            </div>
          {:else}
            <p class="muted">{copyText('subscriptionNone')}</p>
            <a class="btn btn-primary" href="#purchase">{copyText('buyNow')}</a>
          {/if}
        </div>
      </section>

      <section class="card" id="purchase">
        <div class="card-inner stack">
          <div class="section-head">
            <h2 class="title">{copyText('buyCardTitle')}</h2>
            <span class="tiny">{copyText('choosePlan')}</span>
          </div>
          <div class="plan-grid">
            {#each dashboard.plans.plans as plan}
              <article class="plan-card">
                <div class="plan-card-head">
                  <h3 class="title">{plan.units_display} {dashboard.plans.units_label}</h3>
                </div>
                <div class="stack">
                  <div class="info-line"><span class="tiny">{copyText('cashPrice', { value: formatCurrencyValue(plan.cash_price, plan.cash_currency) })}</span></div>
                  <div class="info-line"><span class="tiny">{copyText('starsPrice', { value: formatCurrencyValue(plan.stars_price, plan.stars_currency) })}</span></div>
                </div>
                <div class="button-stack">
                  {#each dashboard.plans.providers as provider}
                    {#if canBuy(plan, provider)}
                      <button class="btn btn-secondary" type="button" on:click={() => purchasePlan(plan, provider)} disabled={busyAction !== null}>
                        {providerButtonLabel(plan, provider)}
                      </button>
                    {/if}
                  {/each}
                </div>
              </article>
            {/each}
          </div>
        </div>
      </section>
    </div>

    <div class="grid tri-grid">
      <section class="card">
        <div class="card-inner stack">
          <div class="section-head">
            <h2 class="title">{copyText('trialCardTitle')}</h2>
          </div>
          {#if dashboard.trial.enabled && dashboard.trial.available}
            <div class="stack">
              <p class="muted">{copyText('trialAvailable')}</p>
              <p class="tiny">{copyText('daysLabel', { value: dashboard.trial.duration_days })} · {formatBytes((dashboard.trial.traffic_limit_gb ?? 0) * (1024 ** 3))}</p>
              <button class="btn btn-primary" type="button" on:click={activateTrial} disabled={busyAction !== null}>{copyText('activateTrial')}</button>
            </div>
          {:else}
            <p class="muted">{copyText('trialUnavailable')}</p>
          {/if}
        </div>
      </section>

      <section class="card">
        <div class="card-inner stack">
          <div class="section-head">
            <h2 class="title">{copyText('promoCardTitle')}</h2>
          </div>
          <input
            class="input"
            type="text"
            bind:value={promoCode}
            placeholder={copyText('promoPlaceholder')}
            autocomplete="off"
          />
          <button class="btn btn-primary" type="button" on:click={applyPromo} disabled={busyAction !== null}>{copyText('applyPromo')}</button>
        </div>
      </section>

      <section class="card">
        <div class="card-inner stack">
          <div class="section-head">
            <h2 class="title">{copyText('referralCardTitle')}</h2>
            <button class="btn btn-secondary" type="button" on:click={() => copyValue(dashboard.referral.link)} disabled={!dashboard.referral.link}>{copyText('referralCopy')}</button>
          </div>
          <div class="metric-grid">
            <div class="metric">
              <span class="tiny">{copyText('invitedUsers', { value: dashboard.referral.stats.invited_count })}</span>
              <strong>{dashboard.referral.stats.invited_count}</strong>
            </div>
            <div class="metric">
              <span class="tiny">{copyText('purchasedUsers', { value: dashboard.referral.stats.purchased_count })}</span>
              <strong>{dashboard.referral.stats.purchased_count}</strong>
            </div>
          </div>
          {#if dashboard.referral.link}
            <div class="info-line">
              <span class="tiny">{copyText('shareReferral')}</span>
              <strong class="truncate">{dashboard.referral.link}</strong>
            </div>
          {:else}
            <p class="muted">{copyText('referralLinkUnavailable')}</p>
          {/if}
        </div>
      </section>
    </div>

    <div class="grid triple-grid">
      <section class="card">
        <div class="card-inner stack">
          <div class="section-head">
            <h2 class="title">{copyText('devicesCardTitle')}</h2>
            <span class="tiny">{dashboard.devices.count}</span>
          </div>
          {#if dashboard.devices.enabled}
            {#if dashboard.devices.items.length}
              <div class="stack">
                {#each dashboard.devices.items as device}
                  <article class="list-item">
                    <div class="list-item-main">
                      <strong>{device.hwid_masked ?? device.hwid ?? '—'}</strong>
                      <p class="tiny">
                        {device.device_model ?? '—'} · {device.platform ?? '—'} · {device.created_at_short ?? formatDate(device.created_at)}
                      </p>
                    </div>
                    <button class="btn btn-secondary" type="button" on:click={() => disconnectDevice(device)} disabled={busyAction !== null}>{copyText('disconnect')}</button>
                  </article>
                {/each}
              </div>
            {:else}
              <p class="muted">{copyText('devicesEmpty')}</p>
            {/if}
          {:else}
            <p class="muted">{copyText('devicesEmpty')}</p>
          {/if}
        </div>
      </section>

      <section class="card">
        <div class="card-inner stack">
          <div class="section-head">
            <h2 class="title">{copyText('paymentMethodsCardTitle')}</h2>
            {#if bootstrap.public.yookassa_autopayments_enabled}
              <button class="btn btn-secondary" type="button" on:click={bindCard} disabled={busyAction !== null}>{copyText('bindCard')}</button>
            {/if}
          </div>
          {#if dashboard.payment_methods.length}
            <div class="stack">
              {#each dashboard.payment_methods as method}
                <article class="list-item">
                  <div class="list-item-main">
                    <div class="inline-tags">
                      <strong>{method.card_network ?? method.provider}</strong>
                      {#if method.is_default}
                        <span class="pill">{copyText('defaultMethod')}</span>
                      {/if}
                    </div>
                    <p class="tiny">{method.card_last4 ? `•••• ${method.card_last4}` : method.provider_payment_method_id}</p>
                    <p class="tiny">{formatDateTime(method.created_at)}</p>
                  </div>
                  <div class="button-stack">
                    {#if !method.is_default}
                      <button class="btn btn-secondary" type="button" on:click={() => setDefaultMethod(method.id)} disabled={busyAction !== null}>{copyText('setDefault')}</button>
                    {/if}
                    <button class="btn btn-secondary" type="button" on:click={() => deleteMethod(method.id)} disabled={busyAction !== null}>{copyText('delete')}</button>
                  </div>
                </article>
              {/each}
            </div>
          {:else}
            <p class="muted">{copyText('paymentMethodsEmpty')}</p>
          {/if}
        </div>
      </section>

      <section class="card">
        <div class="card-inner stack">
          <div class="section-head">
            <h2 class="title">{copyText('paymentsCardTitle')}</h2>
          </div>
          {#if dashboard.payments.length}
            <div class="stack">
              {#each dashboard.payments as payment}
                <article class="list-item">
                  <div class="list-item-main">
                    <div class="inline-tags">
                      <strong>{payment.provider_label}</strong>
                      <span class={`pill ${badgeClass(payment.status)}`}>{payment.status}</span>
                    </div>
                    <p class="tiny">{payment.description ?? payment.provider_payment_id ?? payment.yookassa_payment_id ?? '—'}</p>
                    <p class="tiny">{formatDateTime(payment.created_at)}</p>
                  </div>
                  <div class="metric small-metric">
                    <span class="tiny">{copyText('paymentAmount', { value: payment.amount_display })}</span>
                    <strong>{payment.amount_display} {payment.currency}</strong>
                  </div>
                </article>
              {/each}
            </div>
          {:else}
            <p class="muted">{copyText('paymentsEmpty')}</p>
          {/if}
        </div>
      </section>
    </div>
  {/if}

  <footer class="footer card">
    <div class="card-inner footer-grid">
      {#if bootstrap.public.support_link}
        <a href={bootstrap.public.support_link} target="_blank" rel="noreferrer">{copyText('supportLink')}</a>
      {/if}
      {#if bootstrap.public.privacy_policy_url}
        <a href={bootstrap.public.privacy_policy_url} target="_blank" rel="noreferrer">{copyText('privacyPolicy')}</a>
      {/if}
      {#if bootstrap.public.terms_of_service_url}
        <a href={bootstrap.public.terms_of_service_url} target="_blank" rel="noreferrer">{copyText('termsOfService')}</a>
      {/if}
      {#if bootstrap.public.user_agreement_url}
        <a href={bootstrap.public.user_agreement_url} target="_blank" rel="noreferrer">{copyText('userAgreement')}</a>
      {/if}
    </div>
  </footer>
</div>
