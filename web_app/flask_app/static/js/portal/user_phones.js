function get_user_phones() {
    return $.ajax({type: 'GET', url: '/api/userphones'})
}

function update_user_phones() {
    const card = document.getElementById("phoneCard")
    const status = card.querySelector("#status")
    status.textContent = "...getting phone information"

    // get phones from server and update table
    get_user_phones().then(function (data) {
        console.log(data)

        if (data["success"] == false) {
            status.textContent = "Error: " + data["message"]
        } else {
            status.textContent = ""
            $('#userPhones').DataTable().clear()
            $('#userPhones').DataTable().rows.add(data['rows'])
            $('#userPhones').DataTable().columns.adjust().draw()
        }
    })
}

