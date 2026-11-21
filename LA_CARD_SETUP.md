# LA SHAUNNIE credit-card checkout — staging

## Commercial rules
- LA SHAUNNIE Lash Serum: **US$45 per bottle**.
- **2+ bottles: free shipping** in listed supported delivery destinations.
- 1 bottle to Singapore, Malaysia, Vietnam, Indonesia, Hong Kong: automatically quoted at **Taiwan Post international ePacket Asia** tariff (NT$100 first 100g, +NT$20 per next 100g), currently published April 2026.
- Starting one-bottle packed weight **200g estimate** => **NT$120**. Replace it with the measured packed weight in LA_PACKED_WEIGHT_GRAMS before accepting real orders.
- Optional **SF Express** comparison: only a verified quote entered in LA_SF_QUOTE_TWD_[country], with future LA_SF_QUOTE_VALID_THROUGH, can be selected if cheaper. This is not a live SF API and must not be presented as one.
- Existing Cambodia local QR checkout retains the previously displayed US$3 local delivery for 1 bottle, free for 2+; Taiwan domestic one-bottle delivery needs LA_TW_SHIPPING_TWD.

Official Taiwan Post source: https://subservices.post.gov.tw/post/internet/Postal/index.jsp?ID=1521427719836
Official SF quote page: https://htm.sf-express.com/TW/ZF/dynamic_function/price/

## Owner-only payment setup
1. LA project's Vercel > Settings > Environment Variables: add LA_NEWEBPAY_MERCHANT_ID, LA_NEWEBPAY_HASH_KEY (32-byte), LA_NEWEBPAY_HASH_IV (16-byte). **Never put tokens in chat or GitHub.**
2. Set LA_PUBLIC_URL to LA's actual official HTTPS domain and LA_TWD_PER_USD to the verified exchange rate. Set LA_NEWEBPAY_MODE=test.
3. Confirm existing LA Airtable token and order/customer tables continue working.
4. After merchant approval and sandbox testing, set LA_NEWEBPAY_APPROVED_STORE=true and LA_CARD_ENABLED=true.
5. Test signed notify, duplicate notifications, return page, customer order status; then switch to live credentials.

Card details are entered ONLY on NewebPay. No card numbers are stored by the LA site. The QR/Telegram order flow remains available.

Deployment blocker: The connected Vercel account currently doesn't list the LA deployment project. Production changes and card tests cannot be verified until that project becomes accessible.
