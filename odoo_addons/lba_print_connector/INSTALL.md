# Instalación de LBA Print Connector para Odoo 19 Community

Este ZIP contiene el addon `lba_print_connector` bajo una carpeta con ese mismo nombre. No presupone que la interfaz web de Odoo permita subir cualquier ZIP de módulo.

1. Extraiga el ZIP en un directorio de addons dedicado. Por ejemplo:

   ```bash
   sudo mkdir -p /opt/odoo/custom-addons
   sudo unzip lba-print-connector-odoo19-<commit>.zip -d /tmp/lba-addon-package
   sudo cp -a /tmp/lba-addon-package/lba_print_connector /opt/odoo/custom-addons/
   ```

2. Añada `/opt/odoo/custom-addons` al `addons_path` efectivo de Odoo, conserve las rutas existentes y reinicie el servicio Odoo.
3. Actualice la lista de aplicaciones en una base de QA y verifique las dependencias `point_of_sale` y `pos_restaurant`.
4. Instale `LBA Print Connector` desde Aplicaciones o con el procedimiento administrado por el operador de Odoo.
5. Configure el servidor LBA, el token y las rutas desde el backend Odoo. El servidor debe estar en una LAN autorizada; no exponga el API a Internet. No copie credenciales al repositorio.
6. Haga la primera instalación y upgrade en una base descartable. No ejecute estas instrucciones sobre producción sin respaldo, ventana y aprobación del administrador.

El paquete no contiene Odoo ni instala el servidor LBA. La licencia del proyecto está en `LICENSE`. Consulte el `BUILD-INFO.txt` para identificar el commit del código incluido. La instalación correcta no valida el TPV OWL en navegador, el flujo E2E ni una impresora física.
