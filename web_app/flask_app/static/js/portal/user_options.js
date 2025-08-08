
function get_user_options() {
    return $.ajax({type: 'GET', url: '/api/useroptions'})
}

/**
 * Get user options from the server and update the UI.
 */
function refresh_user_options() {
    // update card with the user options
    const card = document.getElementById('userOptions')

    /**
     * @typedef {Object} data - The data returned from the server
     * @property {boolean} success - Indicates if the request was successful
     * @property {boolean} callIntercept - Indicates if call intercept is enabled
     * @property {boolean} callWaiting - Indicates if call waiting is enabled
     * @property {boolean} callForwarding - Indicates if call forwarding is enabled
     */
    get_user_options().then(function (data) {

        console.log(data)
        if (data.success) {
            card.querySelector('#callIntercept').checked = data.callIntercept
            card.querySelector('#callWaiting').checked = data.callWaiting
        }
    })
}



