"""Delta Dore endpoints and gateway tunables.

pytydom embeds no vendor configuration — the caller provides the cloud
endpoints and transport tunables. This CLI holds them, exactly like the
Home Assistant integration's const.py (values kept verbatim so account-mode
auth behaves identically against the real Delta Dore cloud).
"""

# Delta Dore cloud (account-mode gateway-password lookup).
CLOUD_DISCOVERY_URL = (
    "https://deltadoreadb2ciot.b2clogin.com/deltadoreadb2ciot.onmicrosoft.com"
    "/v2.0/.well-known/openid-configuration?p=B2C_1_AccountProviderROPC_SignIn"
)
CLOUD_SITES_URL = "https://prod.iotdeltadore.com/sitesmanagement/api/v1/sites"
CLOUD_CLIENT_ID = "8782839f-3264-472a-ab87-4d4e23524da4"
CLOUD_SCOPE = (
    "openid profile offline_access"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/video_config"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/video_allowed"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/sites_management_allowed"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi"
    "/sites_management_gateway_credentials"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi"
    "/sites_management_camera_credentials"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/comptage_europe_collect_reader"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi"
    "/comptage_europe_site_config_contributor"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/pilotage_allowed"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/consent_mgt_contributor"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi"
    "/b2caccountprovider_manage_account"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi"
    "/b2caccountprovider_allow_view_account"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/tydom_backend_allowed"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/websocket_remote_access"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_device"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_view"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_space"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_connector"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_endpoint"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/rule_management_allowed"
    " https://deltadoreadb2ciot.onmicrosoft.com/iotapi/collect_read_datas"
)

# Tydom gateway transport.
MEDIATION_HOST = "mediation.tydom.com"
GATEWAY_PORT = 443
REQUEST_TIMEOUT = 60
KEEPALIVE_INTERVAL = 20
