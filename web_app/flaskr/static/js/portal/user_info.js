function get_user_info() {
    return $.ajax({type: 'GET', url: '/userinfo'})
}

function refresh_user_info() {
    // get user info from server and update modal "userinfoModal" accordingly
    get_user_info().then(function (data) {
        console.log(data)
        const modal = document.getElementById("userinfoModal")
        const table = modal.querySelector("#userInfoNumbers");
        const tbody = table.querySelector("tbody");

        // Remove all rows from the table
        while (tbody.firstChild) {
            tbody.removeChild(tbody.firstChild);
        }

        // create one row for each number
        const numbers = data["numbers"];
        numbers.forEach(item => {
            const newRow = document.createElement("tr");

            const cell1 = document.createElement("td");
            cell1.textContent = item["value"];
            newRow.appendChild(cell1);

            const cell2 = document.createElement("td");
            cell2.textContent = item["type"];
            newRow.appendChild(cell2);

            const cell3 = document.createElement("td");
            cell3.textContent = item["primary"];
            newRow.appendChild(cell3);

            tbody.appendChild(newRow);
        })

        // also update the name of the calling location
        const location_name = modal.querySelector("#location_name")
        location_name.textContent = "Location: " + data['location_name']
    });
}