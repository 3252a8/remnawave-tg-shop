import { BackendError, backendGet } from '$lib/server/backend';
import type { BootstrapData, DashboardResponse } from '$lib/types';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const bootstrap = await backendGet<BootstrapData>(event, '/api/web/bootstrap');
  let dashboard = null;
  let dashboardError: string | null = null;

  if (bootstrap.authenticated) {
    try {
      const dashboardResponse = await backendGet<DashboardResponse>(event, '/api/web/dashboard');
      dashboard = dashboardResponse.dashboard ?? null;
    } catch (error) {
      dashboardError =
        error instanceof BackendError
          ? error.message
          : error instanceof Error
            ? error.message
            : 'Failed to load the dashboard.';
    }
  }

  return {
    bootstrap,
    dashboard,
    dashboardError,
    telegramCode: event.url.searchParams.get('telegram_code'),
  };
};
