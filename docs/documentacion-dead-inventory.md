# Sistema de Detección de Stock Inmovilizado

## Documentación Conceptual

---

## 1. Resumen Ejecutivo

El sistema de **Detección de Stock Inmovilizado** es una herramienta analítica diseñada para identificar productos que tienen inventario físico en tienda pero no registran ventas. Este fenómeno representa un problema crítico en retail porque:

- **Capital inmovilizado**: Dinero invertido en productos que no se venden
- **Costo de oportunidad**: Espacio de anaquel ocupado que podría usarse para productos de mayor rotación
- **Riesgo de obsolescencia**: Productos que pueden caducar o pasar de moda

### Entrada del Sistema
- Archivo consolidado con datos históricos de ventas e inventario por producto y tienda

### Salida del Sistema
- Reporte de alertas priorizadas indicando qué productos requieren atención inmediata

---

## 2. Conceptos Clave

### 2.1 Stock Inmovilizado (Dead Inventory)

**Definición**: Un producto se considera "stock inmovilizado" cuando:
- Tiene unidades físicas en el inventario de la tienda (stock > 0)
- No ha registrado ninguna venta en un período determinado (ventas = 0)

El sistema mide los **días consecutivos** en esta condición para determinar la gravedad del problema.

### 2.2 Mala Exhibición

**Definición**: Es una variante del stock inmovilizado que indica un problema específico de visibilidad o accesibilidad del producto.

Se detecta cuando:
- El producto no tiene ventas por varios días
- Durante ese período, el stock **aumentó** (hubo reposición)

**Interpretación**: Si el proveedor o la tienda repuso mercancía pero el producto sigue sin venderse, probablemente el problema es que:
- El producto no está visible en el anaquel
- Está en una ubicación de difícil acceso
- La exhibición no es atractiva

Este tipo de alerta requiere una acción diferente: **revisar la ubicación física del producto** en lugar de evaluar su demanda.

---

## 3. Sistema de Priorización

No todos los productos con stock inmovilizado tienen la misma urgencia. El sistema utiliza un modelo de priorización inteligente basado en la **importancia del producto** y la **importancia de la tienda**.

### 3.1 Clasificación por Quintiles

Los productos y tiendas se clasifican en 5 grupos (quintiles) según su volumen de facturación histórica:

| Quintil | Descripción | Porcentaje de Facturación |
|---------|-------------|---------------------------|
| 1 | Top performers | 0% - 20% (los de mayor venta) |
| 2 | Alto rendimiento | 20% - 40% |
| 3 | Rendimiento medio | 40% - 60% |
| 4 | Bajo rendimiento | 60% - 80% |
| 5 | Menor rendimiento | 80% - 100% |

**Ejemplo**:
- Un producto en Quintil 1 está dentro del top 20% de productos por facturación
- Una tienda en Quintil 1 es una de las tiendas con mayor volumen de ventas

### 3.2 Cálculo de Severidad

La severidad combina la importancia del producto y de la tienda en una escala del 1 al 10:

**Fórmula**: `Severidad = Quintil del Producto + Quintil de la Tienda - 1`

| Q. Producto | Q. Tienda | Severidad | Interpretación |
|-------------|-----------|-----------|----------------|
| 1 | 1 | 1 | Producto top en tienda top - **Máxima prioridad** |
| 1 | 2 | 2 | Producto top en tienda importante |
| 2 | 1 | 2 | Producto importante en tienda top |
| 3 | 3 | 5 | Importancia media |
| 5 | 5 | 9 | Producto y tienda de menor facturación |
| 5 | 5 | 10 | Mínima prioridad |

---

## 4. Umbrales de Alerta

El sistema no genera alertas inmediatamente cuando un producto deja de venderse. En cambio, espera un número de días que varía según la severidad:

| Severidad | Días sin ventas para generar alerta |
|-----------|-------------------------------------|
| 1 | 2 días |
| 2 | 3 días |
| 3 | 4 días |
| 4 | 5 días |
| 5 | 6 días |
| 6 | 7 días |
| 7 | 8 días |
| 8 | 9 días |
| 9 | 10 días |
| 10 | 11 días |

**Lógica**: Los productos más importantes (severidad baja) generan alertas más rápido porque su impacto en el negocio es mayor.

---

## 5. Ejemplo Práctico

### Escenario
- **Producto**: Shampoo Marca X (UPC: 123456789)
- **Tienda**: Sucursal Centro (#42)
- **Situación**: 5 días consecutivos sin ventas, con 15 unidades en stock

### Análisis del Sistema

1. **Clasificación del producto**: El Shampoo Marca X facturó $50,000 en el período histórico, ubicándose en el **Quintil 2** (alto rendimiento)

2. **Clasificación de la tienda**: La Sucursal Centro facturó $2M en total, ubicándose en el **Quintil 1** (top tienda)

3. **Cálculo de severidad**: 2 + 1 - 1 = **Severidad 2**

4. **Umbral aplicable**: Para severidad 2, el umbral es **3 días**

5. **Resultado**: Como el producto lleva 5 días sin ventas (mayor al umbral de 3 días), **SE GENERA ALERTA**

6. **Tipo de alerta**: Si durante estos 5 días el stock subió de 10 a 15 unidades, la alerta será "**Mala Exhibición**". Si el stock se mantuvo o bajó, será "**Stock Inmovilizado**".

---

## 6. Información del Reporte

El reporte generado incluye para cada alerta:

| Campo | Descripción |
|-------|-------------|
| Fecha | Día en que se detectó la alerta |
| Item Nbr | Número interno del producto |
| Item Desc | Descripción del producto |
| UPC | Código universal del producto |
| Store Nbr | Número de tienda |
| Store Name | Nombre de la tienda |
| Alarma | Tipo: "Stock Inmovilizado" o "Mala Exhibición" |
| Sell out Promedio Un. | Promedio histórico de unidades vendidas por día |
| Sell out Promedio $ | Promedio histórico de ventas en pesos por día |
| Días de alarma | Días consecutivos sin ventas |
| Severidad | Nivel de prioridad (1-10) |
| Q. UPC | Quintil del producto |
| Q. Store | Quintil de la tienda |
| In Transit | Unidades en tránsito hacia la tienda |

---

## 7. Recomendaciones de Uso

### Para alertas de "Stock Inmovilizado"
1. Verificar si el producto tiene demanda en otras tiendas
2. Evaluar si es un problema estacional
3. Considerar promociones o transferencias entre tiendas

### Para alertas de "Mala Exhibición"
1. Inspeccionar físicamente la ubicación del producto
2. Verificar que esté visible y accesible
3. Revisar si hay productos competidores bloqueando la vista
4. Considerar mejorar la señalización o el facing

### Priorización
- Atender primero las alertas de **severidad 1-3**
- Las alertas de severidad 8-10 pueden monitorearse pero no requieren acción inmediata

---

## 8. Parámetros Configurables

El sistema permite ajustar:

| Parámetro | Valor Actual | Descripción |
|-----------|--------------|-------------|
| Ventana de historial mínima | 14 días | Mínimo de datos necesarios para el análisis |
| Ventana de historial máxima | 28 días | Período usado para calcular rankings y promedios |
| Umbrales por severidad | 2-11 días | Días sin venta necesarios según prioridad |

---

*Documento generado para uso interno. Sistema de Análisis de Inventario Walmart.*
