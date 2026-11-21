# LA SHAUNNIE credit-card checkout — staging

Merchant settings belong to LA SHAUNNIE and are not copied from ARUNERA.

1. In the LA Vercel project's Settings > Environment Variables, enter LA_NEWEBPAY_MERCHANT_ID, LA_NEWEBPAY_HASH_KEY (32-byte value), and LA_NEWEBPAY_HASH_IV (16-byte value). Do not enter these credentials in chat or GitHub.
2. Set LA_PUBLIC_URL to the official LA HTTPS origin; LA_TWD_PER_USD to the confirmed conversion rate; LA_NEWEBPAY_MODE=test during testing.
3. Set international delivery fee per order (USD): LA_SHIPPING_USD_VN, LA_SHIPPING_USD_SG, LA_SHIPPING_USD_MY, LA_SHIPPING_USD_ID, LA_SHIPPING_USD_TW, LA_SHIPPING_USD_HK. Destinations with no fee remain unavailable to card checkout.
4. Existing LA Airtable token must be configured in the LA Vercel project; card orders use LA's current Orders and Customers tables.
5. After merchant approval and sandbox verification, set LA_NEWEBPAY_APPROVED_STORE=true and LA_CARD_ENABLED=true; test signed notify and payment status.
6. Switch LA_NEWEBPAY_MODE=live only after live merchant credentials and authorization are confirmed.

Do not store card numbers locally. NewebPay hosts the card entry page. Existing local QR/Telegram ordering is unchanged for Cambodia.

Deployment: the currently connected Vercel account does not list the LA project, so the production site cannot be deployed or checked from the available connection. Source changes are staged as a GitHub pull request.