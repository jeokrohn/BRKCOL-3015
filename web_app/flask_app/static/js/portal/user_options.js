function get_user_options() {
    return $.ajax({type: 'GET', url: '/api/useroptions'})
}

function refresh_user_options() {
    // update card with the user options
    const card = document.getElementById('userOptions')

    // get user options from server and update checkboxes
    get_user_options().then(function (data) {
        console.log(data)
        if (data["success"]) {
            card.querySelector('#callIntercept').checked = data['callIntercept']
            card.querySelector('#callWaiting').checked = data['callWaiting']
        }
    })
}



