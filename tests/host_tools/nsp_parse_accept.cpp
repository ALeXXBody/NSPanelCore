// Host tool: parse a register_accept payload with the REAL firmware parser
// (accept_parse.cpp — the exact code running on the panel) and print the
// adopted manager address/port.
// stdin: the JSON payload; stdout: "address<TAB>port<TAB>ok"
#include "../../firmware-native/src/accept_parse.h"
#include <iostream>
#include <string>

int main() {
    std::string payload((std::istreambuf_iterator<char>(std::cin)),
                         std::istreambuf_iterator<char>());
    std::string addr; int port = 0;
    bool ok = nsp_parse_register_accept(payload, addr, port);
    std::cout << addr << "\t" << port << "\t" << (ok ? "ok" : "fail") << std::endl;
    return 0;
}
