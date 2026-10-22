(function () {
    'use strict';

    var formato = new Intl.NumberFormat('es-CO', {
        style: 'currency',
        currency: 'COP',
        maximumFractionDigits: 0
    });

    var CODIGO = /^[0-9]{3}[A-Z]{3}$/;

    var cuerpo = document.querySelector('#tablaProductos tbody');
    var filaVacia = document.getElementById('filaVacia');
    var plantilla = document.getElementById('tplProducto');
    var buscar = document.getElementById('productoBuscar');
    var lista = document.getElementById('comboLista');
    var vacio = document.getElementById('comboVacio');
    var error = document.getElementById('errorCodigo');
    var btnGenerar = document.getElementById('btnGenerar');
    var items = Array.prototype.slice.call(lista.querySelectorAll('li[data-codigo]'));

    /* ---------- Catálogo: sale de la propia lista ---------- */

    var catalogo = {};
    items.forEach(function (li) {
        var precio = Number(li.dataset.precio);
        catalogo[li.dataset.codigo] = {
            id: li.dataset.id,
            codigo: li.dataset.codigo,
            nombre: li.dataset.nombre,
            precio: precio,
            stock: Number(li.dataset.stock)
        };
        if (!catalogo[li.dataset.codigo].stock) { li.classList.add('agotado'); }
        li.querySelector('.combo-precio').textContent = formato.format(precio);
    });

    /* ---------- Combo con búsqueda ---------- */

    function abrir() { lista.hidden = false; }
    function cerrar() { lista.hidden = true; }

    function filtrar() {
        var q = buscar.value.trim().toLowerCase();
        var visibles = 0;
        items.forEach(function (li) {
            var ok = !q ||
                li.dataset.codigo.toLowerCase().indexOf(q) !== -1 ||
                li.dataset.nombre.toLowerCase().indexOf(q) !== -1;
            li.hidden = !ok;
            if (ok) { visibles++; }
        });
        vacio.hidden = visibles > 0;
    }

    function primeroVisible() {
        return items.find(function (li) { return !li.hidden; });
    }

    /* ---------- Tabla de productos ---------- */

    function mostrarError(texto) {
        error.textContent = texto;
        error.hidden = !texto;
    }

    function filas() {
        return cuerpo.querySelectorAll('tr[data-codigo]');
    }

    function actualizar() {
        var total = 0;
        var valido = true;

        var excedidos = [];

        filas().forEach(function (fila) {
            var precio = Number(fila.dataset.precio);
            var input = fila.querySelector('input[name="cantidad"]');
            var cantidad = Number(input.value || 0);
            var subtotal = precio * cantidad;
            var excede = cantidad > Number(fila.dataset.stock);

            input.classList.toggle('excedido', excede);
            if (excede) { excedidos.push(fila.dataset.codigo); valido = false; }

            fila.querySelector('.celda-subtotal').textContent = formato.format(subtotal);
            total += subtotal;
            if (cantidad < 1) { valido = false; }
        });

        filaVacia.hidden = filas().length > 0;
        document.getElementById('totalFactura').textContent = formato.format(total);
        btnGenerar.disabled = !(filas().length > 0 && valido);
        if (excedidos.length) {
            mostrarError('No hay suficientes unidades de: ' + excedidos.join(', ') + '.');
        }
    }

    function agregar(producto) {
        var existente = cuerpo.querySelector('tr[data-codigo="' + producto.codigo + '"]');

        if (!producto.stock) {
            mostrarError('El producto ' + producto.codigo + ' está agotado.');
            return;
        }

        if (existente) {
            var cantidad = existente.querySelector('input[name="cantidad"]');
            cantidad.value = Number(cantidad.value) + 1;
        } else {
            var fila = plantilla.content.firstElementChild.cloneNode(true);
            fila.dataset.codigo = producto.codigo;
            fila.dataset.precio = producto.precio;
            fila.dataset.stock = producto.stock;
            fila.querySelector('input[name="cantidad"]').max = producto.stock;
            fila.querySelector('.celda-stock').textContent = producto.stock;
            fila.querySelector('.celda-codigo').textContent = producto.codigo;
            fila.querySelector('.celda-nombre').textContent = producto.nombre;
            fila.querySelector('.celda-precio').textContent = formato.format(producto.precio);
            fila.querySelector('input[name="producto"]').value = producto.id;
            cuerpo.appendChild(fila);
        }

        buscar.value = '';
        mostrarError('');
        filtrar();
        cerrar();
        actualizar();
    }

    // Botón: exige el código completo
    function agregarCodigo() {
        var texto = buscar.value.trim().toUpperCase();

        if (catalogo[texto]) {
            agregar(catalogo[texto]);
        } else if (!CODIGO.test(texto)) {
            mostrarError('Escribe el código completo (3 números y 3 letras, ej. 123ABC) o elige un producto de la lista.');
        } else {
            mostrarError('No existe un producto con el código ' + texto + '.');
        }
    }

    /* ---------- Eventos ---------- */

    buscar.addEventListener('focus', function () { filtrar(); abrir(); });
    buscar.addEventListener('click', function () { filtrar(); abrir(); });

    buscar.addEventListener('input', function () {
        mostrarError('');
        filtrar();
        abrir();
    });

    buscar.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            var texto = buscar.value.trim().toUpperCase();
            var primero = primeroVisible();

            if (catalogo[texto]) {
                agregar(catalogo[texto]);
            } else if (texto && primero) {
                agregar(catalogo[primero.dataset.codigo]);
            } else {
                agregarCodigo();
            }
        } else if (e.key === 'Escape') {
            cerrar();
        }
    });

    // mousedown (no click) para que se elija antes de que el campo pierda el foco
    lista.addEventListener('mousedown', function (e) {
        var li = e.target.closest('li[data-codigo]');
        if (li) {
            e.preventDefault();
            agregar(catalogo[li.dataset.codigo]);
        }
    });

    document.addEventListener('click', function (e) {
        if (!e.target.closest('#comboProducto')) { cerrar(); }
    });

    document.getElementById('btnAgregarProducto').addEventListener('click', agregarCodigo);

    cuerpo.addEventListener('input', function () { mostrarError(''); actualizar(); });

    cuerpo.addEventListener('click', function (e) {
        var quitar = e.target.closest('.btn-quitar');
        if (!quitar) { return; }
        quitar.closest('tr').remove();
        actualizar();
    });

    actualizar();
})();