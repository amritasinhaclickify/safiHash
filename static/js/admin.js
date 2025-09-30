// static/js/admin.js

// Load all users
fetch("/api/admin/users")
    .then(res => res.json())
    .then(users => {
        const table = document.querySelector("#users-table tbody");
        users.forEach(u => {
            const row = `<tr>
                <td>${u.id}</td>
                <td>${u.username}</td>
                <td>${u.email}</td>
                <td>${u.hedera_id}</td>
            </tr>`;
            table.innerHTML += row;
        });
    });

// Load all loans
fetch("/api/admin/loans")
    .then(res => res.json())
    .then(loans => {
        const table = document.querySelector("#loans-table tbody");
        loans.forEach(loan => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${loan.id}</td>
                <td>${loan.user_id}</td>
                <td>${loan.amount}</td>
                <td>${loan.purpose}</td>
                <td>${loan.status}</td>
                <td>
                    <button onclick="updateStatus(${loan.id}, 'approved')" class="btn btn-sm btn-success">✅ Approve</button>
                    <button onclick="updateStatus(${loan.id}, 'rejected')" class="btn btn-sm btn-danger">❌ Reject</button>
                </td>
            `;
            table.appendChild(row);
        });
    });

// Update loan status
function updateStatus(loanId, status) {
    fetch(`/api/admin/loans/${loanId}/status`, {
        method: "POST",
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status })
    })
    .then(res => res.json())
    .then(data => {
        alert(data.message);
        location.reload();
    });
}
