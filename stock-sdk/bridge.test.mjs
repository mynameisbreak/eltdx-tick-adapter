import assert from 'node:assert/strict';
import test from 'node:test';

import { handle } from './bridge.mjs';

test('dispatches A-share quotes to the documented Stock SDK namespace', async () => {
  const calls = [];
  const sdk = { quotes: { cn: async codes => { calls.push(codes); return [{ code: '000001' }]; } } };

  const result = await handle({ op: 'quotes.cn', codes: ['sz000001'] }, sdk);

  assert.deepEqual(calls, [['sz000001']]);
  assert.deepEqual(result, [{ code: '000001' }]);
});

test('dispatches daily kline with explicit date and no-adjust options', async () => {
  let call;
  const sdk = { kline: { cn: async (symbol, options) => { call = [symbol, options]; return []; } } };

  await handle({
    op: 'kline.cn',
    symbol: '000001.SZ',
    options: { period: 'daily', adjust: '', startDate: '20260901', endDate: '20260930' },
  }, sdk);

  assert.deepEqual(call, ['000001.SZ', {
    period: 'daily', adjust: '', startDate: '20260901', endDate: '20260930',
  }]);
});

test('rejects unknown bridge operations', async () => {
  await assert.rejects(() => handle({ op: 'unknown' }, {}), /unsupported Stock SDK operation/);
});
