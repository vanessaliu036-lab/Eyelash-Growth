/* LA SHAUNNIE hosted card checkout. No card number or merchant secret is entered here. */
(() => {
  const $ = (id) => document.getElementById(id);
  const button = $("cardPayButton");
  const message = $("cardMessage");
  const amount = $("cardAmount");
  const cardResult = $("cardResult");
  const country = $("country");
  const qrArea = $("localPayment");
  const shippingNote = $("shippingNote");
  let currentQuote = null;

  const usd = (v) => "$" + Number(v).toFixed(2);
  const qty = () => Number($("qty").textContent);
  const setMessage = (s) => { message.textContent = s; };

  async function refreshQuote() {
    currentQuote = null;
    button.disabled = true;
    amount.textContent = "Checking availability…";
    const isCambodia = country.value === "KH";
    qrArea.hidden = !isCambodia;
    shippingNote.hidden = !isCambodia;
    if (!isCambodia) {
      $("shipping").textContent = "Checking…";
      $("total").textContent = "Checking…";
    }
    try {
      const response = await fetch(
        "/api/newebpay?action=quote&country=" + encodeURIComponent(country.value) + "&quantity=" + qty(),
        { cache: "no-store" }
      );
      if (!response.ok) throw new Error("Unable to confirm delivery charge");
      const quote = await response.json();
      if (quote.country !== country.value || quote.quantity !== qty()) return;
      currentQuote = quote;
      $("subtotal").textContent = usd(quote.subtotalUsd);
      $("shipping").textContent = quote.freeShipping ? "FREE" : quote.shippingUsd !== null ? usd(quote.shippingUsd) : quote.shippingTwd !== null ? "NT$" + Number(quote.shippingTwd).toLocaleString("en-US") : "To be confirmed";
      $("total").textContent = quote.totalUsd === null ? usd(quote.subtotalUsd) + (quote.shippingTwd !== null ? " + NT$" + quote.shippingTwd + " shipping" : " + shipping") : usd(quote.totalUsd);
      amount.textContent = quote.amountTwd === null ? "TWD total shown after exchange-rate setup" : "NT$" + Number(quote.amountTwd).toLocaleString("en-US");
      $("shippingCarrier").textContent = quote.freeShipping ? "Free international delivery for 2+ bottles." :
        quote.country !== "KH" && quote.country !== "TW" ? "Flat US$6 shipping for one bottle. Shipped from Taiwan." :
        quote.shippingCarrier;
      button.disabled = !quote.enabled;
      if (quote.shippingUsd === null && quote.shippingTwd === null) setMessage("Delivery to this country is not priced yet. Card payment is unavailable.");
      else if (!quote.enabled) setMessage("Secure credit card checkout is being connected. Please check again later.");
      else setMessage("Visa / Mastercard · Secure NewebPay checkout. Your card is charged in TWD.");
    } catch {
      setMessage("Card checkout is temporarily unavailable.");
      if (!isCambodia) { $("shipping").textContent = "To be confirmed"; $("total").textContent = "To be confirmed"; }
    }
  }

  async function payByCard() {
    if (!currentQuote?.enabled || button.disabled) return;
    const values = {};
    const required = [
      ["name", (v) => v.length > 0],
      ["phone", (v) => v.length > 0],
      ["email", (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)],
      ["address", (v) => v.length >= 5]
    ];
    for (const [id, valid] of required) {
      const element = $(id);
      const value = element.value.trim();
      values[id] = value;
      if (!valid(value)) {
        setMessage("Please provide valid " + id + " details.");
        element.focus();
        return;
      }
    }
    button.disabled = true;
    button.textContent = "Opening secure payment…";
    try {
      const response = await fetch("/api/newebpay?action=create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...values, country: country.value, quantity: qty() })
      });
      const checkout = await response.json();
      if (!response.ok) throw new Error(checkout.error || "Unable to start card payment");
      const allowed = [
        "https://core.newebpay.com/MPG/mpg_gateway",
        "https://ccore.newebpay.com/MPG/mpg_gateway"
      ];
      if (!allowed.includes(checkout.action) || checkout.currency !== "TWD" ||
          checkout.amountTwd !== currentQuote.amountTwd || !checkout.fields) {
        throw new Error("Payment quote changed. Please refresh and retry.");
      }
      const form = document.createElement("form");
      form.action = checkout.action;
      form.method = "POST";
      for (const key of ["MerchantID", "TradeInfo", "TradeSha", "Version"]) {
        if (typeof checkout.fields[key] !== "string") throw new Error("Invalid gateway response");
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = key;
        input.value = checkout.fields[key];
        form.appendChild(input);
      }
      document.body.appendChild(form);
      form.submit();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Payment unavailable.");
      button.disabled = false;
      button.textContent = "Pay securely by credit card";
    }
  }

  async function checkOrderStatus(number) {
    if (!/^LA[0-9A-F]{22}$/.test(number)) return;
    cardResult.hidden = false;
    cardResult.textContent = "Checking payment confirmation for " + number + "…";
    try {
      const response = await fetch("/api/newebpay?action=status&order=" + encodeURIComponent(number), { cache: "no-store" });
      const data = await response.json();
      if (data.status === "paid") cardResult.textContent = "Payment confirmed. Order " + number + " is received.";
      else if (data.status === "pending") cardResult.textContent = "Payment verification is pending for order " + number + ". Please refresh to check again.";
      else cardResult.textContent = "Payment could not be verified. Please contact customer service with your order reference.";
    } catch {
      cardResult.textContent = "We could not check payment status. Please try again later.";
    }
  }

  $("minus").addEventListener("click", refreshQuote);
  $("plus").addEventListener("click", refreshQuote);
  country.addEventListener("change", refreshQuote);
  button.addEventListener("click", payByCard);
  refreshQuote();

  const params = new URLSearchParams(location.search);
  if (params.get("payment") === "checking" && params.get("order")) {
    const number = params.get("order");
    checkOrderStatus(number);
    window.setTimeout(() => {
      if (cardResult.textContent.includes("pending")) checkOrderStatus(number);
    }, 4000); // Only one follow-up check; no indefinite polling.
  }
})();
