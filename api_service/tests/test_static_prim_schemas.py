"""
Unit tests for Static Prim data model (Pydantic schemas).

Validates:
  - Vec3, Transform, BoundingBox, PrimMetadata value objects
  - StaticPrimData structured model (creation, defaults, validation)
  - PrimRecord flat model (Iceberg row format)
  - Round-trip: StaticPrimData -> PrimRecord -> StaticPrimData
  - Space_id auto-derivation from prim_path
  - Request / Response schema validation
"""

from __future__ import annotations

import json

import pytest

from app.models.schemas import (
    BoundingBox,
    PrimMetadata,
    PrimRecord,
    StaticPrimCreate,
    StaticPrimBatchCreateRequest,
    StaticPrimBatchCreateResponse,
    StaticPrimCreateResponse,
    StaticPrimData,
    StaticPrimDetailResponse,
    StaticPrimInsertRequest,
    StaticPrimInsertResponse,
    StaticPrimListResponse,
    StaticSpaceSummary,
    Transform,
    Vec3,
)


# =====================================================================
#  Vec3
# =====================================================================

class TestVec3:
    def test_defaults(self):
        v = Vec3()
        assert v.x == 0.0
        assert v.y == 0.0
        assert v.z == 0.0

    def test_custom_values(self):
        v = Vec3(x=1.5, y=-2.3, z=100.0)
        assert v.x == 1.5
        assert v.y == -2.3
        assert v.z == 100.0

    def test_serialization(self):
        v = Vec3(x=1.0, y=2.0, z=3.0)
        d = v.model_dump()
        assert d == {"x": 1.0, "y": 2.0, "z": 3.0}
        assert Vec3(**d) == v


# =====================================================================
#  Transform
# =====================================================================

class TestTransform:
    def test_identity_defaults(self):
        t = Transform()
        assert t.translate == Vec3(x=0.0, y=0.0, z=0.0)
        assert t.rotate == Vec3(x=0.0, y=0.0, z=0.0)
        assert t.scale == Vec3(x=1.0, y=1.0, z=1.0)

    def test_custom_transform(self):
        t = Transform(
            translate=Vec3(x=10, y=20, z=30),
            rotate=Vec3(x=0, y=90, z=0),
            scale=Vec3(x=2, y=2, z=2),
        )
        assert t.translate.x == 10.0
        assert t.rotate.y == 90.0
        assert t.scale.x == 2.0

    def test_round_trip(self):
        t = Transform(
            translate=Vec3(x=1.1, y=2.2, z=3.3),
            rotate=Vec3(x=45, y=90, z=180),
            scale=Vec3(x=0.5, y=1.0, z=2.0),
        )
        d = t.model_dump()
        restored = Transform(**d)
        assert restored == t


# =====================================================================
#  BoundingBox
# =====================================================================

class TestBoundingBox:
    def test_defaults(self):
        bb = BoundingBox()
        assert bb.min == Vec3()
        assert bb.max == Vec3()

    def test_center(self):
        bb = BoundingBox(
            min=Vec3(x=-1, y=-2, z=-3),
            max=Vec3(x=1, y=2, z=3),
        )
        center = bb.center
        assert center.x == pytest.approx(0.0)
        assert center.y == pytest.approx(0.0)
        assert center.z == pytest.approx(0.0)

    def test_extents(self):
        bb = BoundingBox(
            min=Vec3(x=0, y=0, z=0),
            max=Vec3(x=4, y=6, z=8),
        )
        ext = bb.extents
        assert ext.x == pytest.approx(2.0)
        assert ext.y == pytest.approx(3.0)
        assert ext.z == pytest.approx(4.0)

    def test_serialization(self):
        bb = BoundingBox(
            min=Vec3(x=-1, y=-1, z=0),
            max=Vec3(x=1, y=1, z=2),
        )
        d = bb.model_dump()
        assert "min" in d and "max" in d
        restored = BoundingBox(**d)
        assert restored.min == bb.min
        assert restored.max == bb.max


# =====================================================================
#  PrimMetadata
# =====================================================================

class TestPrimMetadata:
    def test_defaults(self):
        m = PrimMetadata()
        assert m.purpose is None
        assert m.visibility is None
        assert m.kind is None
        assert m.material_path is None
        assert m.is_instance is False
        assert m.semantic_label is None
        assert m.custom == {}

    def test_full_metadata(self):
        m = PrimMetadata(
            purpose="render",
            visibility="inherited",
            kind="component",
            material_path="/World/Looks/Mat_01",
            is_instance=True,
            semantic_label="chair",
            layer_identifier="root_layer.usda",
            custom={"weight": 5.0, "color": "red"},
        )
        assert m.purpose == "render"
        assert m.is_instance is True
        assert m.custom["weight"] == 5.0

    def test_custom_extensibility(self):
        """custom dict should accept arbitrary nested data."""
        m = PrimMetadata(custom={
            "sensor_data": {"type": "UWB", "accuracy": 0.15},
            "tags": ["furniture", "static"],
        })
        assert m.custom["sensor_data"]["type"] == "UWB"


# =====================================================================
#  PrimRecord (flat / Iceberg form)
# =====================================================================

class TestPrimRecord:
    def test_creation_with_type_alias(self):
        """PrimRecord accepts 'type' as alias for object_type."""
        r = PrimRecord(prim_path="/World/Room_A/Chair", type="Mesh", properties="{}")
        assert r.object_type == "Mesh"
        assert r.prim_path == "/World/Room_A/Chair"

    def test_creation_with_object_type(self):
        """PrimRecord also accepts object_type directly (populate_by_name)."""
        r = PrimRecord(prim_path="/World/Room_A/Table", object_type="Xform", properties="{}")
        assert r.object_type == "Xform"

    def test_default_properties(self):
        r = PrimRecord(prim_path="/World/X", type="Scope")
        assert r.properties == "{}"


# =====================================================================
#  StaticPrimData (structured form)
# =====================================================================

class TestStaticPrimData:
    def test_minimal_creation(self):
        p = StaticPrimData(
            prim_path="/World/Room_A/Chair_01",
            object_type="Mesh",
        )
        assert p.prim_path == "/World/Room_A/Chair_01"
        assert p.object_type == "Mesh"
        assert p.space_id == "Room_A"  # auto-derived
        assert p.transform.scale == Vec3(x=1, y=1, z=1)
        assert p.child_count == 0

    def test_space_id_auto_derivation(self):
        p = StaticPrimData(prim_path="/World/Lab_B/Rack/Shelf", object_type="Xform")
        assert p.space_id == "Lab_B"

    def test_space_id_explicit_override(self):
        p = StaticPrimData(
            prim_path="/World/Lab_B/Rack",
            object_type="Xform",
            space_id="custom_space",
        )
        assert p.space_id == "custom_space"

    def test_space_id_non_world_path(self):
        """Prim not under /World should get no auto space_id."""
        p = StaticPrimData(prim_path="/Environment/Sky", object_type="Scope")
        assert p.space_id is None

    def test_full_construction(self):
        p = StaticPrimData(
            prim_path="/World/Room_A/Chair_01",
            object_type="Mesh",
            parent_path="/World/Room_A",
            transform=Transform(
                translate=Vec3(x=1.0, y=0.5, z=0.0),
                rotate=Vec3(x=0, y=45, z=0),
                scale=Vec3(x=1, y=1, z=1),
            ),
            bbox=BoundingBox(
                min=Vec3(x=-0.3, y=0.0, z=-0.3),
                max=Vec3(x=0.3, y=0.9, z=0.3),
            ),
            metadata=PrimMetadata(
                purpose="render",
                semantic_label="chair",
                material_path="/World/Looks/Wood",
            ),
            child_count=3,
        )
        assert p.space_id == "Room_A"
        assert p.transform.rotate.y == 45.0
        assert p.bbox.center.y == pytest.approx(0.45)
        assert p.metadata.semantic_label == "chair"
        assert p.child_count == 3

    def test_round_trip_via_prim_record(self):
        """StaticPrimData -> PrimRecord -> StaticPrimData should preserve data."""
        original = StaticPrimData(
            prim_path="/World/Room_A/Table_02",
            object_type="Mesh",
            parent_path="/World/Room_A",
            transform=Transform(
                translate=Vec3(x=5.0, y=0.0, z=3.0),
                rotate=Vec3(x=0, y=90, z=0),
            ),
            bbox=BoundingBox(
                min=Vec3(x=4.0, y=0.0, z=2.0),
                max=Vec3(x=6.0, y=0.8, z=4.0),
            ),
            metadata=PrimMetadata(
                semantic_label="table",
                custom={"legs": 4},
            ),
            child_count=2,
        )

        # Flatten
        flat = original.to_prim_record()
        assert flat.prim_path == "/World/Room_A/Table_02"
        assert flat.object_type == "Mesh"

        # Properties should be valid JSON containing our structured data
        props = json.loads(flat.properties)
        assert "transform" in props
        assert "bbox" in props
        assert "metadata" in props
        assert props["child_count"] == 2

        # Reconstruct
        restored = StaticPrimData.from_prim_record(flat, space_id="Room_A")
        assert restored.prim_path == original.prim_path
        assert restored.object_type == original.object_type
        assert restored.transform.translate.x == pytest.approx(5.0)
        assert restored.transform.rotate.y == pytest.approx(90.0)
        assert restored.bbox.min.x == pytest.approx(4.0)
        assert restored.bbox.max.y == pytest.approx(0.8)
        assert restored.metadata.semantic_label == "table"
        assert restored.metadata.custom["legs"] == 4
        assert restored.child_count == 2

    def test_from_row(self):
        """Reconstruct StaticPrimData from a Trino-style row."""
        columns = ["prim_path", "type", "properties", "space_id", "ingested_at"]
        props = json.dumps({
            "transform": {"translate": {"x": 1, "y": 2, "z": 3}, "rotate": {"x": 0, "y": 0, "z": 0}, "scale": {"x": 1, "y": 1, "z": 1}},
            "bbox": {"min": {"x": 0, "y": 0, "z": 0}, "max": {"x": 2, "y": 2, "z": 2}},
            "metadata": {"semantic_label": "rack"},
            "child_count": 5,
        })
        row = ["/World/Lab/Rack_01", "Xform", props, "Lab", "2026-01-01T00:00:00"]

        p = StaticPrimData.from_row(row, columns)
        assert p.prim_path == "/World/Lab/Rack_01"
        assert p.object_type == "Xform"
        assert p.space_id == "Lab"
        assert p.transform.translate.x == pytest.approx(1.0)
        assert p.bbox.max.z == pytest.approx(2.0)
        assert p.metadata.semantic_label == "rack"
        assert p.child_count == 5

    def test_from_prim_record_with_empty_properties(self):
        """Gracefully handle empty/missing properties JSON."""
        r = PrimRecord(prim_path="/World/X/Y", type="Scope", properties="{}")
        p = StaticPrimData.from_prim_record(r)
        assert p.transform == Transform()
        assert p.metadata == PrimMetadata()

    def test_from_prim_record_with_invalid_json(self):
        """Gracefully handle invalid properties JSON."""
        r = PrimRecord(prim_path="/World/X/Y", type="Scope", properties="not-json")
        p = StaticPrimData.from_prim_record(r)
        assert p.transform == Transform()


# =====================================================================
#  Request / Response schemas
# =====================================================================

class TestStaticPrimInsertRequest:
    def test_valid_request(self):
        req = StaticPrimInsertRequest(records=[
            StaticPrimData(prim_path="/World/Room_A/Chair", object_type="Mesh"),
            StaticPrimData(prim_path="/World/Room_A/Table", object_type="Mesh"),
        ])
        assert len(req.records) == 2
        assert req.space_id is None

    def test_with_space_override(self):
        req = StaticPrimInsertRequest(
            space_id="Room_B",
            records=[
                StaticPrimData(prim_path="/World/Room_A/Chair", object_type="Mesh"),
            ],
        )
        assert req.space_id == "Room_B"

    def test_empty_records_rejected(self):
        with pytest.raises(Exception):  # ValidationError
            StaticPrimInsertRequest(records=[])


class TestStaticPrimInsertResponse:
    def test_response(self):
        resp = StaticPrimInsertResponse(
            inserted=5,
            table="iceberg.static_db.table_a",
            space_ids=["Room_A", "Room_B"],
        )
        assert resp.inserted == 5
        assert len(resp.space_ids) == 2
        assert resp.message == "ok"


class TestStaticPrimDetailResponse:
    def test_detail_response(self):
        prim = StaticPrimData(prim_path="/World/Room_A/Chair", object_type="Mesh")
        resp = StaticPrimDetailResponse(prim=prim)
        assert resp.prim.prim_path == "/World/Room_A/Chair"
        assert resp.ingested_at is None


class TestStaticPrimListResponse:
    def test_list_response(self):
        prims = [
            StaticPrimData(prim_path="/World/Room_A/Chair", object_type="Mesh"),
            StaticPrimData(prim_path="/World/Room_A/Table", object_type="Mesh"),
        ]
        resp = StaticPrimListResponse(
            prims=prims, total_count=50, page_size=10, offset=0, space_id="Room_A",
        )
        assert len(resp.prims) == 2
        assert resp.total_count == 50
        assert resp.space_id == "Room_A"


class TestStaticSpaceSummary:
    def test_space_summary(self):
        bb = BoundingBox(
            min=Vec3(x=-10, y=0, z=-10),
            max=Vec3(x=10, y=3, z=10),
        )
        s = StaticSpaceSummary(
            space_id="Room_A",
            prim_count=42,
            type_distribution={"Mesh": 30, "Xform": 10, "Scope": 2},
            bbox_envelope=bb,
        )
        assert s.prim_count == 42
        assert s.type_distribution["Mesh"] == 30
        assert s.bbox_envelope.center.y == pytest.approx(1.5)


# =====================================================================
#  StaticPrimCreate (API request schema)
# =====================================================================

class TestStaticPrimCreate:
    """Tests for the StaticPrimCreate request model."""

    def test_minimal_creation(self):
        """Minimal required fields: prim_path and prim_type."""
        p = StaticPrimCreate(
            prim_path="/World/Room_A/Chair_01",
            prim_type="Mesh",
        )
        assert p.prim_path == "/World/Room_A/Chair_01"
        assert p.prim_type == "Mesh"
        assert p.space_id == "Room_A"  # auto-derived
        assert p.transform == Transform()
        assert p.bbox == BoundingBox()
        assert p.properties == PrimMetadata()
        assert p.child_count == 0

    def test_space_id_auto_derivation(self):
        """space_id should be auto-derived from prim_path."""
        p = StaticPrimCreate(prim_path="/World/Lab_B/Rack/Shelf", prim_type="Xform")
        assert p.space_id == "Lab_B"

    def test_space_id_explicit_override(self):
        """Explicit space_id should not be overridden."""
        p = StaticPrimCreate(
            prim_path="/World/Lab_B/Rack",
            prim_type="Xform",
            space_id="custom_zone",
        )
        assert p.space_id == "custom_zone"

    def test_space_id_non_world_path(self):
        """Prim not under /World should have no auto space_id."""
        p = StaticPrimCreate(prim_path="/Environment/Sky", prim_type="Scope")
        assert p.space_id is None

    def test_full_construction(self):
        """All fields populated."""
        p = StaticPrimCreate(
            prim_path="/World/Room_A/Chair_01",
            prim_type="Mesh",
            parent_path="/World/Room_A",
            transform=Transform(
                translate=Vec3(x=1.0, y=0.5, z=0.0),
                rotate=Vec3(x=0, y=45, z=0),
                scale=Vec3(x=1, y=1, z=1),
            ),
            bbox=BoundingBox(
                min=Vec3(x=-0.3, y=0.0, z=-0.3),
                max=Vec3(x=0.3, y=0.9, z=0.3),
            ),
            properties=PrimMetadata(
                purpose="render",
                semantic_label="chair",
                material_path="/World/Looks/Wood",
                custom={"weight_kg": 3.5},
            ),
            child_count=3,
        )
        assert p.space_id == "Room_A"
        assert p.prim_type == "Mesh"
        assert p.transform.rotate.y == 45.0
        assert p.bbox.center.y == pytest.approx(0.45)
        assert p.properties.semantic_label == "chair"
        assert p.properties.custom["weight_kg"] == 3.5
        assert p.child_count == 3

    def test_prim_path_required(self):
        """prim_path is required and must be non-empty."""
        with pytest.raises(Exception):
            StaticPrimCreate(prim_type="Mesh")

    def test_prim_type_required(self):
        """prim_type is required and must be non-empty."""
        with pytest.raises(Exception):
            StaticPrimCreate(prim_path="/World/Room_A/Chair")

    def test_empty_prim_path_rejected(self):
        """Empty string for prim_path should be rejected (min_length=1)."""
        with pytest.raises(Exception):
            StaticPrimCreate(prim_path="", prim_type="Mesh")

    def test_empty_prim_type_rejected(self):
        """Empty string for prim_type should be rejected (min_length=1)."""
        with pytest.raises(Exception):
            StaticPrimCreate(prim_path="/World/X", prim_type="")

    def test_negative_child_count_rejected(self):
        """child_count must be >= 0."""
        with pytest.raises(Exception):
            StaticPrimCreate(
                prim_path="/World/X/Y",
                prim_type="Mesh",
                child_count=-1,
            )

    def test_to_static_prim_data_conversion(self):
        """StaticPrimCreate -> StaticPrimData conversion."""
        create = StaticPrimCreate(
            prim_path="/World/Room_A/Table_02",
            prim_type="Mesh",
            parent_path="/World/Room_A",
            transform=Transform(translate=Vec3(x=5.0, y=0.0, z=3.0)),
            bbox=BoundingBox(
                min=Vec3(x=4.0, y=0.0, z=2.0),
                max=Vec3(x=6.0, y=0.8, z=4.0),
            ),
            properties=PrimMetadata(semantic_label="table"),
            child_count=2,
        )
        data = create.to_static_prim_data()
        assert isinstance(data, StaticPrimData)
        assert data.prim_path == "/World/Room_A/Table_02"
        assert data.object_type == "Mesh"  # prim_type -> object_type
        assert data.space_id == "Room_A"
        assert data.parent_path == "/World/Room_A"
        assert data.transform.translate.x == pytest.approx(5.0)
        assert data.bbox.max.y == pytest.approx(0.8)
        assert data.metadata.semantic_label == "table"
        assert data.child_count == 2

    def test_to_prim_record_conversion(self):
        """StaticPrimCreate -> PrimRecord (flat Iceberg row)."""
        create = StaticPrimCreate(
            prim_path="/World/Lab/Rack_01",
            prim_type="Xform",
            properties=PrimMetadata(kind="component", custom={"slots": 8}),
            child_count=4,
        )
        record = create.to_prim_record()
        assert isinstance(record, PrimRecord)
        assert record.prim_path == "/World/Lab/Rack_01"
        assert record.object_type == "Xform"
        props = json.loads(record.properties)
        assert "transform" in props
        assert "bbox" in props
        assert "metadata" in props
        assert props["metadata"]["kind"] == "component"
        assert props["metadata"]["custom"]["slots"] == 8
        assert props["child_count"] == 4

    def test_round_trip_create_to_data_to_record_and_back(self):
        """Full round-trip: Create -> StaticPrimData -> PrimRecord -> StaticPrimData."""
        create = StaticPrimCreate(
            prim_path="/World/Room_A/Desk_01",
            prim_type="Mesh",
            parent_path="/World/Room_A",
            transform=Transform(
                translate=Vec3(x=2.0, y=0.0, z=1.0),
                rotate=Vec3(x=0, y=180, z=0),
                scale=Vec3(x=1.5, y=1.0, z=1.5),
            ),
            bbox=BoundingBox(
                min=Vec3(x=1.0, y=0.0, z=0.0),
                max=Vec3(x=3.0, y=0.8, z=2.0),
            ),
            properties=PrimMetadata(
                semantic_label="desk",
                material_path="/World/Looks/Oak",
                custom={"drawers": 3},
            ),
            child_count=5,
        )

        # Create -> PrimRecord
        record = create.to_prim_record()

        # PrimRecord -> StaticPrimData
        restored = StaticPrimData.from_prim_record(record, space_id="Room_A")

        assert restored.prim_path == create.prim_path
        assert restored.object_type == create.prim_type
        assert restored.space_id == "Room_A"
        assert restored.transform.translate.x == pytest.approx(2.0)
        assert restored.transform.rotate.y == pytest.approx(180.0)
        assert restored.transform.scale.x == pytest.approx(1.5)
        assert restored.bbox.min.x == pytest.approx(1.0)
        assert restored.bbox.max.y == pytest.approx(0.8)
        assert restored.metadata.semantic_label == "desk"
        assert restored.metadata.material_path == "/World/Looks/Oak"
        assert restored.metadata.custom["drawers"] == 3
        assert restored.child_count == 5

    def test_serialization_json(self):
        """Model should serialize to JSON cleanly."""
        p = StaticPrimCreate(
            prim_path="/World/Room_A/Lamp",
            prim_type="Mesh",
            properties=PrimMetadata(semantic_label="lamp"),
        )
        d = p.model_dump()
        assert d["prim_path"] == "/World/Room_A/Lamp"
        assert d["prim_type"] == "Mesh"
        assert d["properties"]["semantic_label"] == "lamp"
        assert d["space_id"] == "Room_A"
        # Round-trip via dict
        restored = StaticPrimCreate(**d)
        assert restored.prim_path == p.prim_path
        assert restored.prim_type == p.prim_type


# =====================================================================
#  StaticPrimBatchCreateRequest
# =====================================================================

class TestStaticPrimBatchCreateRequest:
    def test_valid_batch(self):
        req = StaticPrimBatchCreateRequest(prims=[
            StaticPrimCreate(prim_path="/World/Room_A/Chair", prim_type="Mesh"),
            StaticPrimCreate(prim_path="/World/Room_A/Table", prim_type="Mesh"),
        ])
        assert len(req.prims) == 2
        assert req.space_id is None
        # Each prim should have auto-derived space_id
        assert req.prims[0].space_id == "Room_A"

    def test_space_id_override(self):
        """Top-level space_id should propagate to prims without one."""
        req = StaticPrimBatchCreateRequest(
            space_id="Override_Zone",
            prims=[
                StaticPrimCreate(prim_path="/Custom/Path", prim_type="Scope"),
            ],
        )
        assert req.prims[0].space_id == "Override_Zone"

    def test_space_id_does_not_override_explicit(self):
        """Top-level space_id should NOT override prims that already have one."""
        req = StaticPrimBatchCreateRequest(
            space_id="Override_Zone",
            prims=[
                StaticPrimCreate(
                    prim_path="/World/Room_A/Chair",
                    prim_type="Mesh",
                    # space_id auto-derived to "Room_A" before batch override
                ),
            ],
        )
        # The auto-derived space_id is set before batch override runs,
        # so it will keep "Room_A" because it's not None
        assert req.prims[0].space_id == "Room_A"

    def test_empty_prims_rejected(self):
        with pytest.raises(Exception):
            StaticPrimBatchCreateRequest(prims=[])


# =====================================================================
#  StaticPrimCreateResponse / StaticPrimBatchCreateResponse
# =====================================================================

class TestStaticPrimCreateResponse:
    def test_response(self):
        resp = StaticPrimCreateResponse(
            prim_path="/World/Room_A/Chair",
            prim_type="Mesh",
            space_id="Room_A",
            table="iceberg.static_db.static_prims",
        )
        assert resp.prim_path == "/World/Room_A/Chair"
        assert resp.prim_type == "Mesh"
        assert resp.message == "ok"


class TestStaticPrimBatchCreateResponse:
    def test_response(self):
        resp = StaticPrimBatchCreateResponse(
            inserted=10,
            table="iceberg.static_db.static_prims",
            space_ids=["Room_A", "Lab_B"],
        )
        assert resp.inserted == 10
        assert len(resp.space_ids) == 2
        assert resp.failed == []
        assert resp.message == "ok"

    def test_response_with_failures(self):
        resp = StaticPrimBatchCreateResponse(
            inserted=8,
            table="iceberg.static_db.static_prims",
            space_ids=["Room_A"],
            failed=["/World/Room_A/BadPrim_01", "/World/Room_A/BadPrim_02"],
        )
        assert resp.inserted == 8
        assert len(resp.failed) == 2
