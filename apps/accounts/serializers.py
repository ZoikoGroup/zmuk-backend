from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import authenticate


# ---------------- REGISTER    dd----------------
class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ("email", "username", "password", "password2")

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})
        if User.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError({"email": "Email already registered"})
        return attrs

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
            # is_active=False  # inactive until email verification
        )
        return user


# ---------------- LOGIN ----------------
class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        try:
            user_obj = User.objects.get(email=data["email"])
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid credentials")

        user = authenticate(
            username=user_obj.username,
            password=data["password"]
        )

        if not user:
            raise serializers.ValidationError("Invalid credentials")

        if not user.is_active:
            raise serializers.ValidationError("Account is not activated")

        return user


# ---------------- FORGOT PASSWORD ----------------
class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


# ---------------- RESET PASSWORD ----------------
class ResetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return attrs


# ---------------- UPDATE PROFILE ----------------
# class UpdateUserSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = User
#         fields = ["username", "email", "first_name", "last_name"]

#     def validate_email(self, value):
#         user = self.context['request'].user
#         if User.objects.exclude(pk=user.pk).filter(email=value).exists():
#             raise serializers.ValidationError("Email already in use")
#         return value

# serializers.py
class UpdateUserSerializer(serializers.ModelSerializer):
    bq_enrollment_id = serializers.CharField(
        source='profile.bq_enrollment_id',  # points to profile model
        required=False,
        allow_blank=True
    )

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "bq_enrollment_id"]

    def validate_email(self, value):
        user = self.context['request'].user
        if User.objects.exclude(pk=user.pk).filter(email=value).exists():
            raise serializers.ValidationError("Email already in use")
        return value

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})
        vc_id = profile_data.get('bq_enrollment_id')

        # Update User fields
        instance = super().update(instance, validated_data)

        # Update VC ID if provided
        if vc_id is not None:
            instance.profile.bq_enrollment_id = vc_id
            instance.profile.save()

        return instance
