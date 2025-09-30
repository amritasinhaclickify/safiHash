// static/js/dashboard.js

document.addEventListener("DOMContentLoaded", () => {
    const userId = 1; // Replace with dynamic user ID if needed

    fetch(`/api/finance/wallet/${userId}`)
        .then(res => res.json())
        .then(data => {
            document.getElementById("wallet-balance").textContent = `$${data.balance}`;
        });

    fetch(`/api/users/notifications/${userId}`)
        .then(res => res.json())
        .then(notifs => {
            const container = document.getElementById("dashboard-notifications");
            if (notifs.length === 0) {
                container.textContent = "No notifications";
            } else {
                container.innerHTML = notifs.map(n =>
                    `<div><strong>${n.message}</strong> <small>(${n.timestamp})</small></div>`
                ).join('');
            }
        });

    fetch(`/chat/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: "trust score" })
    })
        .then(res => res.json())
        .then(data => {
            document.getElementById("trust-score").textContent = data.response;
        });
});
