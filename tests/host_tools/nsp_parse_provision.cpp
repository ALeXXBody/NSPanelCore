// Host tool: parse a /provision body with the REAL firmware parser
// (provision_parse.cpp — the exact code running on the panel) and print
// the extracted fields as machine-readable output.
// stdin: the JSON body; stdout: "server<TAB>port<TAB>user<TAB>pass<TAB>ok"
#include "../../firmware-native/src/provision_parse.h"
#include <iostream>
#include <string>

int main() {
    std::string body((std::istreambuf_iterator<char>(std::cin)),
                      std::istreambuf_iterator<char>());
    std::string server, port, user, pass;
    bool s = nsp_provision_field(body, "mqtt_server", server);
    bool p = nsp_provision_field(body, "mqtt_port", port);
    bool u = nsp_provision_field(body, "mqtt_user", user);
    bool w = nsp_provision_field(body, "mqtt_pass", pass);
    std::cout << server << "\t" << port << "\t" << user << "\t" << pass
              << "\t" << (s && u && w ? "ok" : "partial") << std::endl;
    return 0;
}
