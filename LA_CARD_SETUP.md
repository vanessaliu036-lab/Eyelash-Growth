# LA SHAUNNIE credit-card checkout — staging

## Commercial rules
- Product price: **US$45 per bottle**.
- **One bottle to Singapore, Malaysia, Vietnam, Indonesia or Hong Kong: fixed US$6 shipping**, total **US$51**.
- **Two or more bottles: FREE shipping**, two-bottle total **US$90**.
- These shipping amounts are the **buyer-facing charges**, independent of the actual carrier cost.
- Taiwan Post international ePacket estimate (starting with a provisional 200g packed weight) and valid SF Express quotes are retained for **internal carrier-cost comparison only**. The customer still pays the fixed US$6 if buying one bottle.
- Cambodia local QR checkout continues its previous US$3 local delivery for one bottle, free for two or more. Taiwan domestic one-bottle shipping still uses LA_TW_SHIPPING_TWD.
- Hosted-card payment continues to convert the USD total into TWD using LA_TWD_PER_USD; customer-facing total remains in USD.

Official postal tariff: https://subservices.post.gov.tw/post/internet/Postal/index.jsp?ID=1521427719836

## Owner-only payment setup
1. LA project's Vercel > Settings > Environment Variables: add LA_NEWEBPAY_MERCHANT_ID, LA_NEWEBPAY_HASH_KEY (32-byte), LA_NEWEBPAY_HASH_IV (16-byte). **Never put tokens in chat or GitHub.**
2. Set LA_PUBLIC_URL to LA's actual official HTTPS domain and LA_TWD_PER_USD to the verified exchange rate. Set LA_NEWEBPAY_MODE=test.
3. Confirm existing LA Airtable token and order/customer tables continue working.
4. After merchant approval and sandbox testing, set LA_NEWEBPAY_APPROVED_STORE=true and LA_CARD_ENABLED=true.
5. Test signed notify, duplicate notifications, return page, customer order status; then switch to live credentials.

Card details are entered ONLY on NewebPay. No card numbers are stored by the LA site. The QR/Telegram order flow remains available.

Deployment blocker: The connected Vercel account currently doesn't list the LA deployment project. Production changes and card tests cannot be verified until that project becomes accessible.
