"""Configuration service for normalization settings with caching."""
import json
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.batch_job import NormalizationConfig, SupplierRule
from app.core.redis_client import redis_client


class ConfigService:
    """Manage normalization configuration with Redis caching."""

    # Cache keys
    MODALITY_CONFIG_KEY = "normalization:config:{modality}"
    SUPPLIER_RULE_KEY = "supplier:rule:{supplier}:{version}"
    ACTIVE_SUPPLIERS_KEY = "supplier:active:list"
    CACHE_TTL = 300  # 5 minutes

    @staticmethod
    async def get_modality_config(
        session: AsyncSession,
        modality: str,
        use_cache: bool = True,
    ) -> Optional[NormalizationConfig]:
        """
        Load normalization config for a specific modality.

        Args:
            session: Database session
            modality: DICOM modality (CT, MR, US, XR, etc.)
            use_cache: Whether to use Redis cache

        Returns:
            NormalizationConfig or None if not found
        """
        # Try cache first
        if use_cache:
            cache_key = ConfigService.MODALITY_CONFIG_KEY.format(modality=modality)
            cached = await redis_client.get(cache_key)
            if cached:
                return NormalizationConfig._from_cache(json.loads(cached))

        # Query database
        stmt = select(NormalizationConfig).where(
            NormalizationConfig.modality == modality
        )
        result = await session.execute(stmt)
        config = result.scalars().first()

        # Cache result if found
        if config and use_cache:
            cache_key = ConfigService.MODALITY_CONFIG_KEY.format(modality=modality)
            await redis_client.setex(
                cache_key,
                ConfigService.CACHE_TTL,
                json.dumps(config._to_cache()),
            )

        return config

    @staticmethod
    async def get_supplier_rules(
        session: AsyncSession,
        supplier: str,
        use_cache: bool = True,
    ) -> list[SupplierRule]:
        """
        Load active supplier-specific normalization rules.

        Args:
            session: Database session
            supplier: Supplier name (siemens, ge, philips, etc.)
            use_cache: Whether to use Redis cache

        Returns:
            List of active SupplierRule objects
        """
        # Try cache first
        if use_cache:
            cache_key = ConfigService.SUPPLIER_RULE_KEY.format(supplier=supplier, version="*")
            # For supplier list, we'll use a simple list cache
            list_cache_key = f"supplier:rules:{supplier}"
            cached = await redis_client.get(list_cache_key)
            if cached:
                return SupplierRule._from_cache_list(json.loads(cached))

        # Query database for active rules
        stmt = select(SupplierRule).where(
            (SupplierRule.supplier_name == supplier) &
            (SupplierRule.is_active == True)
        ).order_by(SupplierRule.rule_version.desc())

        result = await session.execute(stmt)
        rules = result.scalars().all()

        # Cache results if found
        if rules and use_cache:
            list_cache_key = f"supplier:rules:{supplier}"
            await redis_client.setex(
                list_cache_key,
                ConfigService.CACHE_TTL,
                json.dumps([rule._to_cache() for rule in rules]),
            )

        return rules

    @staticmethod
    async def get_active_suppliers(
        session: AsyncSession,
        use_cache: bool = True,
    ) -> list[str]:
        """
        Get list of suppliers with active rules.

        Args:
            session: Database session
            use_cache: Whether to use Redis cache

        Returns:
            List of supplier names
        """
        # Try cache first
        if use_cache:
            cached = await redis_client.get(ConfigService.ACTIVE_SUPPLIERS_KEY)
            if cached:
                return json.loads(cached)

        # Query database for unique active suppliers
        stmt = select(SupplierRule.supplier_name).where(
            SupplierRule.is_active == True
        ).distinct()

        result = await session.execute(stmt)
        suppliers = [row[0] for row in result.all()]

        # Cache results
        if use_cache:
            await redis_client.setex(
                ConfigService.ACTIVE_SUPPLIERS_KEY,
                ConfigService.CACHE_TTL,
                json.dumps(suppliers),
            )

        return suppliers

    @staticmethod
    async def update_modality_config(
        session: AsyncSession,
        modality: str,
        algorithms: dict,
        risk_tiers: dict,
        updated_by: str,
    ) -> NormalizationConfig:
        """
        Create or update modality configuration.

        Args:
            session: Database session
            modality: DICOM modality
            algorithms: Algorithm enable/disable settings
            risk_tiers: Risk tier handling (safe/medium/risky)
            updated_by: User who made the update

        Returns:
            Updated NormalizationConfig
        """
        # Try to get existing
        stmt = select(NormalizationConfig).where(
            NormalizationConfig.modality == modality
        )
        result = await session.execute(stmt)
        config = result.scalars().first()

        if config:
            # Update existing
            config.algorithms = algorithms
            config.risk_tiers = risk_tiers
            config.updated_by = updated_by
        else:
            # Create new
            config = NormalizationConfig(
                modality=modality,
                algorithms=algorithms,
                risk_tiers=risk_tiers,
                updated_by=updated_by,
            )
            session.add(config)

        await session.flush()

        # Invalidate cache
        cache_key = ConfigService.MODALITY_CONFIG_KEY.format(modality=modality)
        await redis_client.delete(cache_key)

        return config

    @staticmethod
    async def create_supplier_rule(
        session: AsyncSession,
        supplier_name: str,
        rule_version: str,
        rule_config: dict,
        managed_by: str,
        description: Optional[str] = None,
    ) -> SupplierRule:
        """
        Create a new supplier-specific rule.

        Args:
            session: Database session
            supplier_name: Supplier name (siemens, ge, philips, etc.)
            rule_version: Version identifier
            rule_config: Rule configuration (JSON)
            managed_by: User managing the rule
            description: Optional description

        Returns:
            Created SupplierRule
        """
        rule = SupplierRule(
            supplier_name=supplier_name,
            rule_version=rule_version,
            rule_config=rule_config,
            managed_by=managed_by,
            description=description,
            is_active=True,
        )
        session.add(rule)
        await session.flush()

        # Invalidate supplier rules cache
        list_cache_key = f"supplier:rules:{supplier_name}"
        await redis_client.delete(list_cache_key)
        await redis_client.delete(ConfigService.ACTIVE_SUPPLIERS_KEY)

        return rule

    @staticmethod
    async def deactivate_supplier_rule(
        session: AsyncSession,
        rule_id: str,
    ) -> SupplierRule:
        """
        Deactivate a supplier rule (soft delete).

        Args:
            session: Database session
            rule_id: Rule UUID

        Returns:
            Updated SupplierRule
        """
        stmt = select(SupplierRule).where(SupplierRule.id == rule_id)
        result = await session.execute(stmt)
        rule = result.scalars().first()

        if not rule:
            raise ValueError(f"Rule not found: {rule_id}")

        rule.is_active = False
        await session.flush()

        # Invalidate cache
        list_cache_key = f"supplier:rules:{rule.supplier_name}"
        await redis_client.delete(list_cache_key)
        await redis_client.delete(ConfigService.ACTIVE_SUPPLIERS_KEY)

        return rule

    @staticmethod
    async def clear_config_cache() -> None:
        """Clear all config-related caches."""
        # This would clear all modality configs and supplier rules
        # Implementation depends on how redis_client handles pattern deletion
        await redis_client.delete(ConfigService.ACTIVE_SUPPLIERS_KEY)
        # Note: Individual modality/supplier caches will expire naturally
