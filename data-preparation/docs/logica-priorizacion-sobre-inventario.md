# Lógica de Priorización: Sobre-Inventario vs Dead Inventory

## 1. Contexto

Este documento describe la lógica de priorización para las alarmas de **Sobre-Inventario**, comparándola con la lógica existente de **Dead Inventory**.

---

## 2. Dead Inventory (Lógica Actual)

### Definición
Productos sin ventas pero con stock disponible en tienda.

### Lógica de Priorización
- **Producto importante + Tienda importante = Mayor prioridad**
- **Razón**: Perder ventas de productos/tiendas top tiene mayor impacto en facturación

### Fórmula
```
severidad = Q.Producto + Q.Tienda - 1
```
Donde Q1 = mejor quintil (mayor facturación)

| Q.Producto | Q.Tienda | Severidad |
|------------|----------|-----------|
| 1 (top)    | 1 (top)  | **1** (máxima) |
| 1          | 5        | 5 |
| 5          | 1        | 5 |
| 5 (bajo)   | 5 (bajo) | **9** (mínima) |

---

## 3. Sobre-Inventario (Nueva Lógica)

### Definición
Situación donde un producto en una tienda tiene mucho más inventario del que debería, medido en **DOH (Days On Hand)**.

```
DOH = Stock Actual / Promedio de Ventas Diarias
```

### Ejemplo
- Producto X vende 20 unidades/día en Tienda A
- Lead Time: 5 días
- Inventario óptimo: ~120 unidades (6 DOH)
- Si tiene 1,800 unidades → 90 DOH → **Sobre-inventario**

### Impacto
| Plazo | Impacto |
|-------|---------|
| Corto | Capital inmovilizado (problema del retail) |
| Mediano/Largo | Riesgo de descatalogación o liquidación forzada (problema del fabricante) |

### Acción Requerida
Conseguir **exhibición adicional** (cabeceras, islas) para aumentar el sell-out y reducir el inventario.

---

## 4. Diferencia Clave en Priorización

### ¿Por qué la lógica es diferente?

| Aspecto | Dead Inventory | Sobre-Inventario |
|---------|----------------|------------------|
| Problema principal | Pérdida de ventas | Capital inmovilizado / Descatalogación |
| Productos top (Q1) | Urgente resolver | Se autocorrigen (alta rotación) |
| Productos lentos (Q5) | Menos urgente | **MUY urgente** (no se moverán solos) |
| Tiendas grandes | Más impacto si no se resuelve | **Más oportunidad** de exhibición adicional |

---

## 5. Lógica Propuesta para Sobre-Inventario

### Fórmula Recomendada
```
prioridad = (6 - Q.Producto) + Q.Tienda - 1
```

Se **invierte el quintil del producto** pero se mantiene el de tienda.

### Tabla de Prioridades

| Escenario | Q.Producto | Invertido | Q.Tienda | Prioridad |
|-----------|------------|-----------|----------|-----------|
| Producto lento + Tienda grande | Q5 | 1 | Q1 | **1** (crítico) |
| Producto lento + Tienda mediana | Q5 | 1 | Q3 | **3** |
| Producto lento + Tienda pequeña | Q5 | 1 | Q5 | **5** (medio) |
| Producto medio + Tienda grande | Q3 | 3 | Q1 | **3** |
| Producto rápido + Tienda grande | Q1 | 5 | Q1 | **5** (medio) |
| Producto rápido + Tienda pequeña | Q1 | 5 | Q5 | **9** (bajo) |

### Justificación

1. **Productos lentos son la prioridad real**
   - Alto riesgo de descatalogación
   - No se van a mover solos
   - Requieren acción inmediata

2. **Tiendas grandes primero**
   - Mayor tráfico = más oportunidad de sell-out
   - Más espacio para exhibición adicional
   - Mayor impacto si se logra rotar el inventario

3. **Productos rápidos en tiendas grandes tienen prioridad media**
   - El exceso se moverá eventualmente por alta rotación
   - Pero una exhibición adicional puede acelerar la rotación

---

## 6. Consideración Adicional: Factor DOH

Para casos donde la severidad del sobre-inventario varíe mucho, se puede usar el DOH como criterio secundario de ordenamiento:

```
factor_severidad = DOH_actual / DOH_umbral
```

**Ejemplo:**
- Producto A: 90 DOH (umbral 30) → factor = 3.0
- Producto B: 45 DOH (umbral 30) → factor = 1.5

Ambos con misma prioridad base → ordenar por factor descendente.

---

## 7. Resumen Visual

```
DEAD INVENTORY                    SOBRE-INVENTARIO

Prod Top + Tienda Top = P1        Prod Lento + Tienda Grande = P1
         ↓                                    ↓
    (resolver primero)                (resolver primero)
         ↓                                    ↓
Prod Bajo + Tienda Baja = P9      Prod Rápido + Tienda Pequeña = P9
```

---

## 8. Implementación

El nuevo script `generate-overstock.js` implementará esta lógica, reutilizando:
- Cálculo de quintiles por facturación (igual que dead inventory)
- Estructura de agrupación por UPC + Store
- Sistema de umbrales configurable en `settings.json`

Y añadiendo:
- Cálculo de DOH (Days On Hand)
- Lógica de priorización invertida para productos
- Umbrales de DOH configurables por prioridad
