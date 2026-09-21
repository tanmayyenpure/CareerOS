// Tab switching
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
  });
});

// Auto-format card number with spaces
const cardInput = document.getElementById("card_number");
cardInput.addEventListener("input", () => {
  let digits = cardInput.value.replace(/\D/g, "").slice(0, 16);
  cardInput.value = digits.replace(/(.{4})/g, "$1 ").trim();
});

const payBtn = document.getElementById("pay-btn");
const statusMsg = document.getElementById("status-msg");

payBtn.addEventListener("click", async () => {
  const activeTab = document.querySelector(".tab-btn.active").dataset.tab;
  const simulate_result = document.getElementById("simulate_result").value;

  const payload = { order_id: ORDER_ID, method: activeTab, simulate_result };

  if (activeTab === "card") {
    payload.card_number = document.getElementById("card_number").value;
    payload.card_expiry = document.getElementById("card_expiry").value;
    payload.card_cvv = document.getElementById("card_cvv").value;
  } else if (activeTab === "upi") {
    payload.upi_id = document.getElementById("upi_id").value;
  } else if (activeTab === "wallet") {
    payload.wallet_provider = document.getElementById("wallet_provider").value;
  }

  payBtn.disabled = true;
  payBtn.textContent = "Processing...";
  statusMsg.textContent = "Contacting bank / UPI network (simulated)...";
  statusMsg.className = "";

  try {
    // Fake network delay so it feels like a real gateway
    await new Promise((r) => setTimeout(r, 1200));

    const res = await fetch("/api/process-payment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (!res.ok) {
      statusMsg.textContent = data.error || "Something went wrong.";
      statusMsg.className = "error";
      payBtn.disabled = false;
      payBtn.textContent = "Retry Payment";
      return;
    }

    window.location.href = data.redirect_url;
  } catch (err) {
    statusMsg.textContent = "Network error. Please try again.";
    statusMsg.className = "error";
    payBtn.disabled = false;
    payBtn.textContent = "Retry Payment";
  }
});
