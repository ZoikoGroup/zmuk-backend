from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import StudentDiscountSerializer

class StudentDiscountCreateAPIView(APIView):

    def post(self, request):
        serializer = StudentDiscountSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": "Application submitted successfully"},
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
