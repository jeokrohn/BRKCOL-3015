function get_user_queues() {
    return $.ajax({type: 'GET', url: '/userqueues'})
}

function update_user_queues() {
    const card = document.getElementById('queueCard')
    const status = card.querySelector("#status")
    status.textContent = "...getting queue information"

    // get queue information from server and update table
    get_user_queues().then(function (data) {
        console.log(data)

        if (data["success"] == false) {
            status.textContent = "Error: " + data["message"]
        } else {
            status.textContent = ""
            $('#userQueues').DataTable().clear()
            $('#userQueues').DataTable().rows.add(data['rows'])
            $('#userQueues').DataTable().columns.adjust().draw()
        }
    })
}

