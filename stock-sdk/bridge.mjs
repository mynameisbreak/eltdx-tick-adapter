import { pathToFileURL } from 'node:url';
import { StockSDK } from 'stock-sdk';

export async function handle(request, sdk) {
  switch (request.op) {
    case 'quotes.cn':
      if (!Array.isArray(request.codes) || request.codes.length === 0) {
        throw new Error('codes must be a non-empty array');
      }
      return sdk.quotes.cn(request.codes);
    case 'quotes.cnSimple':
      if (!Array.isArray(request.codes) || request.codes.length === 0) {
        throw new Error('codes must be a non-empty array');
      }
      return sdk.quotes.cnSimple(request.codes);
    case 'kline.cn':
      return sdk.kline.cn(request.symbol, request.options);
    case 'kline.cnMinute':
      return sdk.kline.cnMinute(request.symbol, request.options);
    default:
      throw new Error(`unsupported Stock SDK operation: ${request.op}`);
  }
}

async function main() {
  let request;
  try {
    request = JSON.parse(await new Promise((resolve, reject) => {
      let input = '';
      process.stdin.setEncoding('utf8');
      process.stdin.on('data', chunk => { input += chunk; });
      process.stdin.on('end', () => resolve(input));
      process.stdin.on('error', reject);
    }));
    const result = await handle(request, new StockSDK());
    process.stdout.write(JSON.stringify({ ok: true, result }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }));
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
