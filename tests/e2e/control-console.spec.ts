import { test, expect } from '@playwright/test';

test('UI can reset, configure, and apply faults', async ({ page, request, baseURL }) => {
    /**
     * why do we do an API reset first:
     * - UI tests should star from a known, deterministic state.
     * - clicking "reset" in the UI would also work, but using the API here removes any dependency on the UI itself for initial setup
     * - this reduces flakiness when tests run in CI or whne reusing an existing server
     */
    const r = await request.post(`${baseURL}/control/reset`);
    expect(r.ok()).toBeTruthy();
    /**
     * navigate directly to the UI contro console route
     * this page is expected to:
     * - render the current device state (derived from /health)
     * - provide buttons that call control-plane nedpoints (/control/*)
     * - display raw JSON response for debugging / observability
     */
    await page.goto('/ui');

    /**
     * basic UI sanity check
     * the console should populate # state from /health. Depending on timing and
     * internal simulator behavior, it should be one of the known states
     */
    await expect(page.locator('#state')).toHaveText(/IDLE|CONFIGURED|STREAMING/);

    /**
     * click "configure" in the UI
     * intended behavior:
     * - UI sends POST /control/configure
     * - simulator transitions to CONFIGURED
     * - UI refreshed /health and updates the displayed state
     */
    await page.click('#configure');
    await expect(page.locator('#state')).toHaveText('CONFIGURED');

    /**
     * apply a fault profile through the UI
     * intended behavior:
     * - UI sends POST /control/faults with a JSON body
     * - simulator stores the fault profile and uses it to perturb UDP behavior
     * 
     * notes:
     * - drop rate: fraction of packets to drop (0.0 - 1.0)
     * - delay_ms: fixed delay applied to packets
     * - corrupt_rate: fraction of packets to corrupt (CRC/frame failures)
     */
    await page.fill('#drop_rate', '0.70');
    await page.fill('#delay_ms', '100');
    await page.fill('#corrupt_rate', '0.00');
    await page.click('#applyFaults');

    /**
     * asser the UI reflects the applied faults
     * this assumes the backend exposes a GET /control/faults endpoint and the UI 
     * calls it to populate #faultsView
     * 
     * if you *don't* have GET /control/faults:
     * - remove this block, and instead assert #controlResult contains HTTP 200
     * and/or the echoed JSOn response from POST /control/faults
     */
    const faultsText = page.locator('#faultsView');
    await expect(faultsText).toContainText('drop_rate');
    await expect(faultsText).toContainText('0.7');

    /**
     * reset via UI and verify state returns to IDLE
     * contract question (you decide):
     * - does reset also clear faults? or do failuts persist until explicitly cleared?
     * either is fine, but test should encode the inteded contract
     * 
     * here we only assert state returns to IDLE, which is the minimal safe check.
     */
    await page.click('#reset');
    await expect(page.locator('#state')).toHaveText('IDLE');
});
