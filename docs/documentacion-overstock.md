# Sistema de Deteccion de Sobre-Inventario (Overstock)

## Documentacion Conceptual

---

## 1. Resumen Ejecutivo

El sistema de **Deteccion de Sobre-Inventario** es una herramienta analitica disenada para identificar productos que tienen exceso de inventario en relacion a su velocidad de venta. Este fenomeno representa un problema critico en retail porque:

- **Capital inmovilizado**: Dinero excesivo invertido en inventario que rota lentamente
- **Costo de almacenamiento**: Mayor espacio de bodega ocupado innecesariamente
- **Riesgo de obsolescencia**: Productos que pueden caducar, danarse o pasar de moda
- **Costo de oportunidad**: Fondos que podrian invertirse en productos de mayor rotacion

### Entrada del Sistema
- Archivo consolidado con datos historicos de ventas e inventario por producto y tienda

### Salida del Sistema
- Reporte de alertas priorizadas indicando que productos tienen exceso de inventario y su impacto economico

---

## 2. Conceptos Clave

### 2.1 Sobre-Inventario (Overstock)

**Definicion**: Un producto se considera en "sobre-inventario" cuando tiene mas stock del necesario para cubrir la demanda esperada en un periodo razonable.

**A diferencia del Stock Inmovilizado**: El sobre-inventario aplica a productos que SI se venden, pero tienen demasiadas unidades en relacion a su velocidad de venta.

### 2.2 DOH (Days On Hand) - Dias de Inventario

**Definicion**: El DOH indica cuantos dias de venta cubre el inventario actual al ritmo de ventas historico.

**Formula**:
```
DOH = Stock Actual / Promedio de Unidades Vendidas por Dia
```

**Ejemplo**:
- Stock actual: 100 unidades
- Promedio de ventas: 5 unidades/dia
- DOH = 100 / 5 = **20 dias**

Esto significa que con el inventario actual, se cubren 20 dias de venta.

### 2.3 Umbral de Sobre-Inventario

El sistema considera que hay sobre-inventario cuando:

| Condicion | Valor por Defecto |
|-----------|-------------------|
| DOH mayor a | 40 dias |
| Durante al menos | 7 dias consecutivos |

**Interpretacion**: Si un producto tiene inventario para mas de 40 dias de venta, y esta situacion persiste por al menos una semana, se genera una alerta.

### 2.4 Impacto Economico

El sistema calcula el valor monetario del inventario en situacion de sobre-inventario:

**Formula**:
```
Impacto Economico = Precio Unitario Promedio x Stock Actual
```

Donde:
```
Precio Unitario Promedio = Ventas Promedio ($) / Unidades Vendidas Promedio
```

Este valor permite priorizar acciones: atender primero los casos con mayor capital inmovilizado.

---

## 3. Sistema de Priorizacion

Al igual que el sistema de stock inmovilizado, el sobre-inventario utiliza un modelo de priorizacion basado en la **importancia del producto** y la **importancia de la tienda**.

### 3.1 Clasificacion por Quintiles

Los productos y tiendas se clasifican en 5 grupos (quintiles) segun su volumen de facturacion historica:

| Quintil | Descripcion | Porcentaje de Facturacion |
|---------|-------------|---------------------------|
| 1 | Top performers | 0% - 20% (los de mayor venta) |
| 2 | Alto rendimiento | 20% - 40% |
| 3 | Rendimiento medio | 40% - 60% |
| 4 | Bajo rendimiento | 60% - 80% |
| 5 | Menor rendimiento | 80% - 100% |

### 3.2 Calculo de Severidad

La severidad combina la importancia del producto y de la tienda en una escala del 1 al 10:

**Formula**: `Severidad = Quintil del Producto + Quintil de la Tienda - 1`

| Q. Producto | Q. Tienda | Severidad | Interpretacion |
|-------------|-----------|-----------|----------------|
| 1 | 1 | 1 | Producto top en tienda top - **Maxima prioridad** |
| 1 | 2 | 2 | Producto top en tienda importante |
| 2 | 1 | 2 | Producto importante en tienda top |
| 3 | 3 | 5 | Importancia media |
| 5 | 5 | 9 | Producto y tienda de menor facturacion |
| 5 | 5 | 10 | Minima prioridad |

---

## 4. Criterios de Ordenamiento del Reporte

Las alertas se ordenan por multiples criterios para facilitar la priorizacion:

| Prioridad | Criterio | Orden | Razon |
|-----------|----------|-------|-------|
| 1ro | Severidad | Ascendente | Productos mas importantes primero |
| 2do | Impacto Economico | Descendente | Mayor capital inmovilizado primero |
| 3ro | Dias en situacion | Descendente | Problemas mas antiguos primero |

---

## 5. Ejemplo Practico

### Escenario
- **Producto**: Detergente Marca Y (UPC: 987654321)
- **Tienda**: Sucursal Norte (#15)
- **Stock actual**: 200 unidades
- **Promedio de ventas**: 4 unidades/dia

### Analisis del Sistema

1. **Calculo de DOH**: 200 / 4 = **50 dias**

2. **Evaluacion vs umbral**: 50 > 40 dias? **SI, hay sobre-inventario**

3. **Verificacion de persistencia**: La situacion ha durado 10 dias consecutivos (> 7 dias minimo) **SI cumple**

4. **Clasificacion del producto**: El Detergente Marca Y factura $30,000 en el periodo, ubicandose en el **Quintil 3**

5. **Clasificacion de la tienda**: Sucursal Norte factura $800K en total, ubicandose en el **Quintil 2**

6. **Calculo de severidad**: 3 + 2 - 1 = **Severidad 4**

7. **Calculo de impacto economico**:
   - Precio unitario promedio = $50 / 4 = $12.50 por unidad
   - Impacto = $12.50 x 200 = **$2,500** de capital inmovilizado

### Resultado
Se genera alerta con:
- DOH: 50 dias
- Dias en situacion: 10
- Severidad: 4
- Impacto economico: $2,500

---

## 6. Diferencia entre Sobre-Inventario y Stock Inmovilizado

| Aspecto | Stock Inmovilizado | Sobre-Inventario |
|---------|-------------------|------------------|
| Ventas | Cero ventas | Si hay ventas |
| Problema | Producto no rota | Producto rota lento vs. stock |
| Metrica | Dias sin venta | DOH (dias de inventario) |
| Accion tipica | Revisar exhibicion o demanda | Ajustar reabastecimiento |

**Importante**: Un producto **no puede** estar en ambas alertas simultaneamente. Si tiene ventas = 0, es stock inmovilizado. Si tiene ventas > 0 pero DOH alto, es sobre-inventario.

---

## 7. Informacion del Reporte

El reporte generado incluye para cada alerta:

| Campo | Descripcion |
|-------|-------------|
| Fecha | Dia en que se detecto la alerta |
| Item Nbr | Numero interno del producto |
| Item Desc | Descripcion del producto |
| UPC | Codigo universal del producto |
| Store Nbr | Numero de tienda |
| Store Name | Nombre de la tienda |
| DOH | Dias de inventario actual |
| Dias en situacion | Dias consecutivos en sobre-inventario |
| Severidad | Nivel de prioridad (1-10) |
| Q. UPC | Quintil del producto |
| Q. Store | Quintil de la tienda |
| Impacto Economico | Valor monetario del stock |
| Stock | Unidades fisicas en tienda |
| Promedio Ventas Un. | Unidades promedio vendidas por dia |
| Promedio Ventas $ | Ventas promedio en pesos por dia |

---

## 8. Recomendaciones de Uso

### Acciones sugeridas para sobre-inventario

1. **Reducir pedidos**: Ajustar el punto de reorden para este producto/tienda
2. **Transferencias**: Mover inventario a tiendas con mayor demanda
3. **Promociones**: Acelerar la rotacion con ofertas o descuentos
4. **Revision de forecast**: Verificar si las proyecciones de demanda son correctas

### Priorizacion

- **Severidad 1-3**: Accion inmediata - productos importantes con alto impacto
- **Severidad 4-6**: Monitorear y planificar acciones
- **Severidad 7-10**: Revisar en proxima planificacion de inventario

### Indicadores de exito

- Reduccion del DOH promedio
- Disminucion del numero de alertas
- Reduccion del impacto economico total

---

## 9. Parametros Configurables

El sistema permite ajustar:

| Parametro | Valor Actual | Descripcion |
|-----------|--------------|-------------|
| DOH Threshold | 40 dias | Umbral de dias de inventario para considerar sobre-inventario |
| Min Days Threshold | 7 dias | Dias minimos en situacion para generar alerta |
| Ventana de historial minima | 14 dias | Minimo de datos necesarios para el analisis |
| Ventana de historial maxima | 28 dias | Periodo maximo usado para calcular promedios |

---

*Documento generado para uso interno. Sistema de Analisis de Inventario Walmart.*
