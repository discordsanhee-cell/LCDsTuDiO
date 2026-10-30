import 'package:flet/flet.dart';

import 'lcd_ble.dart';

class Extension extends FletExtension {
  @override
  FletService? createService(Control control) {
    switch (control.type) {
      case "LcdBle":
        return LcdBleService(control: control);
      default:
        return null;
    }
  }
}
